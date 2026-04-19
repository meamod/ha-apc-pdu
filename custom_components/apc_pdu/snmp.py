"""SNMPv3 client for APC PDU outlet control."""
from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    get_cmd,
    set_cmd,
)
# Integer32 lives in the protocol layer, not the hlapi convenience re-exports
from pysnmp.proto.rfc1902 import Integer32

# SNMP exception values returned inside varBinds (not as errorIndication/errorStatus)
from pysnmp.proto.rfc1905 import NoSuchInstance, NoSuchObject, EndOfMibView

# All auth/priv protocol constants are guaranteed present in pysnmp >= 7.0
from pysnmp.hlapi.v3arch import (
    usmNoAuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmHMAC128SHA224AuthProtocol,
    usmHMAC192SHA256AuthProtocol,
    usmHMAC256SHA384AuthProtocol,
    usmHMAC384SHA512AuthProtocol,
    usmNoPrivProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
)

from .const import (
    OID_OUTLET_NAME,
    OID_OUTLET_CONTROL,
    OID_LOAD_AMPS,
    OID_LOAD_STATE,
    OID_IDENT_NAME,
    OID_IDENT_MODEL,
    OID_IDENT_SERIAL,
    OID_IDENT_FIRMWARE,
    OID_IDENT_DATE_OF_MANUFACTURE,
    OID_IDENT_NUM_OUTLETS,
    CMD_IMMEDIATE_ON,
    CMD_IMMEDIATE_OFF,
)

AUTH_PROTOCOL_MAP = {
    "none":    usmNoAuthProtocol,
    "MD5":     usmHMACMD5AuthProtocol,
    "SHA":     usmHMACSHAAuthProtocol,
    "SHA-224": usmHMAC128SHA224AuthProtocol,
    "SHA-256": usmHMAC192SHA256AuthProtocol,
    "SHA-384": usmHMAC256SHA384AuthProtocol,
    "SHA-512": usmHMAC384SHA512AuthProtocol,
}

PRIV_PROTOCOL_MAP = {
    "none":    usmNoPrivProtocol,
    "DES":     usmDESPrivProtocol,
    "AES-128": usmAesCfb128Protocol,
    "AES-192": usmAesCfb192Protocol,
    "AES-256": usmAesCfb256Protocol,
}

# (OID, result-key, is_integer) for the single bulk GET in get_device_ident()
_IDENT_FIELDS: list[tuple[str, str, bool]] = [
    (OID_IDENT_NAME,             "name",             False),
    (OID_IDENT_MODEL,            "model",            False),
    (OID_IDENT_SERIAL,           "serial",           False),
    (OID_IDENT_FIRMWARE,         "firmware",         False),
    (OID_IDENT_DATE_OF_MANUFACTURE, "manufacture_date", False),
    (OID_IDENT_NUM_OUTLETS,      "num_outlets",      True),
]


def _decode_octet_string(val) -> str:
    """Decode a pysnmp OctetString / DisplayString value to a plain string."""
    raw: bytes = val.asOctets() if hasattr(val, "asOctets") else bytes(val)
    return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip()


class APCPDUClient:
    """Thin async wrapper around SNMPv3 GET/SET for APC PDU outlets."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        auth_protocol: str,
        auth_key: str,
        priv_protocol: str,
        priv_key: str,
    ) -> None:
        self._host = host
        self._port = port
        self._engine = SnmpEngine()
        self._preload_dispatch_mibs()

        self._auth = UsmUserData(
            username,
            authKey=auth_key or None,
            privKey=priv_key or None,
            authProtocol=AUTH_PROTOCOL_MAP.get(auth_protocol, usmNoAuthProtocol),
            privProtocol=PRIV_PROTOCOL_MAP.get(priv_protocol, usmNoPrivProtocol),
        )
        self._context = ContextData()
        # Serialise all SNMP operations — the shared SnmpEngine is not safe for
        # concurrent use.  Without this lock a coordinator poll racing with a
        # SET corrupts the engine's request-id tracking.
        self._lock = asyncio.Lock()
        # Cached transport — created once on first use and reused thereafter.
        self._transport_cache: UdpTransportTarget | None = None

    def _preload_dispatch_mibs(self) -> None:
        """Pre-load the MIBs that pysnmp's message dispatcher uses internally.

        pysnmp's ``receive_message`` (rfc3412) calls
        ``mib_instrum_controller.get_mib_builder().import_symbols(
            "__SNMPv2-MIB", "snmpInPkts", ...)``
        on *every* received packet to update SNMP statistics counters.

        ``import_symbols`` checks ``self.mibSymbols`` before doing any I/O —
        if the module is already there it returns immediately.  Loading here
        (inside ``__init__``, which is called from an executor thread) populates
        ``mibSymbols`` so that all event-loop callbacks are instant cache hits
        with no file I/O and no HA blocking-call warnings.

        The correct pysnmp 7.x API is ``get_mib_builder()`` (snake_case).
        The old ``getMibBuilder()`` does not exist in 7.x and would raise
        ``AttributeError``, silently swallowed by a bare ``except Exception``.
        """
        try:
            mb = self._engine.get_mib_builder()
            # Core modules whose symbols receive_message() looks up.
            mb.load_modules(
                "SNMPv2-MIB",    # snmpInPkts, snmpInBadVersions, etc.
                "SNMPv2-SMI",    # base types
                "SNMPv2-TC",     # TextualConvention
                "SNMP-MPD-MIB",  # snmpUnknownPDUHandlers
            )
            # Instance files (double-underscore prefix) may be loaded as side-
            # effects of the above; load explicitly to guarantee coverage.
            for inst_mod in ("__SNMPv2-MIB", "__SNMP-MPD-MIB"):
                try:
                    mb.load_modules(inst_mod)
                except Exception:  # noqa: BLE001
                    pass  # not present in all pysnmp builds — safe to skip
            _LOGGER.debug("pysnmp dispatch MIBs pre-loaded — event-loop I/O eliminated")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MIB pre-load failed (SNMP will still work): %s", err)

    async def _transport(self) -> UdpTransportTarget:
        """Return a cached transport target, creating it on first call."""
        if self._transport_cache is None:
            self._transport_cache = await UdpTransportTarget.create(
                (self._host, self._port), timeout=5, retries=2
            )
        return self._transport_cache

    def close(self) -> None:
        """Release resources (call on integration unload)."""
        self._transport_cache = None

    # ------------------------------------------------------------------
    # Single-OID helpers (used for config-flow validation and startup)
    # ------------------------------------------------------------------

    async def get_outlet_state(self, outlet: int) -> bool:
        """Return True if the outlet is on, False if off."""
        oid = f"{OID_OUTLET_CONTROL}.{outlet}"
        _LOGGER.debug("GET %s (outlet %s)", oid, outlet)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                ObjectType(ObjectIdentity(oid)),
            )
        if errorIndication:
            raise RuntimeError(f"SNMP error: {errorIndication}")
        if errorStatus:
            raise RuntimeError(
                f"SNMP error: {errorStatus.prettyPrint()} at index {errorIndex}"
            )
        if not varBinds:
            raise RuntimeError(f"GET outlet {outlet} — empty response")
        _, val = varBinds[0]
        _LOGGER.debug("GET outlet %s — value: %s  type: %s", outlet, val.prettyPrint(), type(val).__name__)
        if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
            raise RuntimeError(
                f"OID {oid} returned {type(val).__name__} — "
                "check the OID is correct for this PDU model and that the "
                "SNMPv3 user has read access"
            )
        return int(val) == 1  # 1=on, 2=off

    async def _get_integer_oid(self, oid: str) -> int | None:
        """GET a single integer-valued OID; return None on any error."""
        _LOGGER.debug("GET %s", oid)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                ObjectType(ObjectIdentity(oid)),
            )
        if errorIndication or errorStatus:
            return None
        for _, val in varBinds:
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                return None
            try:
                return int(val)
            except (TypeError, ValueError):
                return None
        return None

    async def _get_string_oid(self, oid: str) -> str:
        """GET a single string-valued OID; return empty string on any error."""
        _LOGGER.debug("GET %s", oid)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                ObjectType(ObjectIdentity(oid)),
            )
        if errorIndication or errorStatus:
            return ""
        for _, val in varBinds:
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                return ""
            return _decode_octet_string(val)
        return ""

    async def get_pdu_name(self) -> str:
        """Return the PDU's configured name (rPDUIdentName), or empty string."""
        return await self._get_string_oid(OID_IDENT_NAME)

    async def get_num_outlets(self) -> int | None:
        """Return the outlet count reported by the PDU, or None if unavailable."""
        val = await self._get_integer_oid(OID_IDENT_NUM_OUTLETS)
        return val if val and val > 0 else None

    # ------------------------------------------------------------------
    # Bulk GET methods — fetch multiple OIDs in a single SNMP request
    # ------------------------------------------------------------------

    async def get_all_outlet_states(self, count: int) -> dict[int, bool]:
        """Return outlet states for all outlets in a single SNMP GET request."""
        outlets = list(range(1, count + 1))
        _LOGGER.debug("GET outlet states (bulk, count=%s)", count)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                *(ObjectType(ObjectIdentity(f"{OID_OUTLET_CONTROL}.{o}")) for o in outlets),
            )
        if errorIndication:
            raise RuntimeError(f"SNMP error: {errorIndication}")
        if errorStatus:
            raise RuntimeError(
                f"SNMP error: {errorStatus.prettyPrint()} at index {errorIndex}"
            )
        result: dict[int, bool] = {}
        for outlet, (_, val) in zip(outlets, varBinds):
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                raise RuntimeError(
                    f"OID {OID_OUTLET_CONTROL}.{outlet} returned {type(val).__name__} — "
                    "check the OID is correct for this PDU model and that the "
                    "SNMPv3 user has read access"
                )
            result[outlet] = int(val) == 1
        return result

    async def get_outlet_names(self, count: int) -> dict[int, str]:
        """Return outlet names for all outlets in a single SNMP GET request."""
        outlets = list(range(1, count + 1))
        _LOGGER.debug("GET outlet names (bulk, count=%s)", count)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                *(ObjectType(ObjectIdentity(f"{OID_OUTLET_NAME}.{o}")) for o in outlets),
            )
        if errorIndication or errorStatus:
            _LOGGER.debug("Could not read outlet names — falling back to defaults")
            return {}
        result: dict[int, str] = {}
        for outlet, (_, val) in zip(outlets, varBinds):
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                result[outlet] = ""
                continue
            # Only accept string types — an Integer here means the name OID
            # is not supported on this model.
            if type(val).__name__ not in ("OctetString", "DisplayString"):
                result[outlet] = ""
                continue
            result[outlet] = _decode_octet_string(val)
        return result

    async def get_device_ident(self) -> dict[str, str]:
        """Return PDU identity fields in a single SNMP GET request.

        Keys: name, model, serial, firmware, manufacture_date, num_outlets.
        Any value that cannot be read is returned as an empty string.
        """
        _LOGGER.debug("GET device identity (bulk)")
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                *(ObjectType(ObjectIdentity(oid)) for oid, _, _ in _IDENT_FIELDS),
            )
        result = {key: "" for _, key, _ in _IDENT_FIELDS}
        if errorIndication or errorStatus:
            return result
        for (_, key, is_int), (_, val) in zip(_IDENT_FIELDS, varBinds):
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                continue
            if is_int:
                try:
                    n = int(val)
                    result[key] = str(n) if n > 0 else ""
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    result[key] = _decode_octet_string(val)
                except Exception:  # noqa: BLE001
                    pass
        return result

    async def get_load_metrics(self) -> tuple[float | None, int | None]:
        """Return (amps, load_state) from a single SNMP GET request.

        amps: total PDU current in Amps (PDU reports tenths; divided by 10), or None.
        load_state: integer 1–4 (Low Load / Normal / Near Overload / Overload), or None.
        Both are None when the OID is unsupported or an SNMP error occurs.
        """
        _LOGGER.debug("GET load metrics (bulk)")
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                ObjectType(ObjectIdentity(OID_LOAD_AMPS)),
                ObjectType(ObjectIdentity(OID_LOAD_STATE)),
            )
        if errorIndication or errorStatus:
            return None, None
        amps: float | None = None
        state: int | None = None
        if len(varBinds) >= 1:
            _, amp_val = varBinds[0]
            if not isinstance(amp_val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                try:
                    raw = int(amp_val)
                    if raw >= 0:
                        amps = round(raw / 10, 1)
                except (TypeError, ValueError):
                    pass
        if len(varBinds) >= 2:
            _, state_val = varBinds[1]
            if not isinstance(state_val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                try:
                    state = int(state_val)
                except (TypeError, ValueError):
                    pass
        return amps, state

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def set_outlet(self, outlet: int, state: bool) -> None:
        """Send immediateOn or immediateOff to the specified outlet."""
        if outlet < 1:
            raise ValueError(f"Outlet number must be >= 1, got {outlet}")
        oid = f"{OID_OUTLET_CONTROL}.{outlet}"
        value = Integer32(CMD_IMMEDIATE_ON if state else CMD_IMMEDIATE_OFF)
        _LOGGER.debug("SET %s = %s (outlet %s -> %s)", oid, value, outlet, "on" if state else "off")
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
                self._engine, self._auth, await self._transport(), self._context,
                ObjectType(ObjectIdentity(oid), value),
            )
        if errorIndication:
            raise RuntimeError(f"SNMP error: {errorIndication}")
        if errorStatus:
            raise RuntimeError(
                f"SNMP error: {errorStatus.prettyPrint()} at index {errorIndex}"
            )
        _LOGGER.debug("SET outlet %s -> %s OK", outlet, "on" if state else "off")
