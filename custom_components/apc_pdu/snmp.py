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

# Core auth protocols — available in all pysnmp 6.x builds
from pysnmp.hlapi.v3arch import (
    usmNoAuthProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmNoPrivProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
)

# Extended SHA-2 auth protocols — present in pysnmp 6.x but guard anyway
try:
    from pysnmp.hlapi.v3arch import (
        usmHMAC128SHA224AuthProtocol,
        usmHMAC192SHA256AuthProtocol,
        usmHMAC256SHA384AuthProtocol,
        usmHMAC384SHA512AuthProtocol,
    )
except ImportError:
    usmHMAC128SHA224AuthProtocol = usmHMACSHAAuthProtocol  # type: ignore[assignment]
    usmHMAC192SHA256AuthProtocol = usmHMACSHAAuthProtocol  # type: ignore[assignment]
    usmHMAC256SHA384AuthProtocol = usmHMACSHAAuthProtocol  # type: ignore[assignment]
    usmHMAC384SHA512AuthProtocol = usmHMACSHAAuthProtocol  # type: ignore[assignment]

# Extended AES priv protocols — guard for the same reason
try:
    from pysnmp.hlapi.v3arch import usmAesCfb192Protocol, usmAesCfb256Protocol
except ImportError:
    usmAesCfb192Protocol = usmAesCfb128Protocol  # type: ignore[assignment]
    usmAesCfb256Protocol = usmAesCfb128Protocol  # type: ignore[assignment]

from .const import OID_OUTLET_NAME, OID_OUTLET_STATUS, OID_OUTLET_CONTROL, CMD_IMMEDIATE_ON, CMD_IMMEDIATE_OFF

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
        self._auth = UsmUserData(
            username,
            authKey=auth_key or None,
            privKey=priv_key or None,
            authProtocol=AUTH_PROTOCOL_MAP.get(auth_protocol, usmNoAuthProtocol),
            privProtocol=PRIV_PROTOCOL_MAP.get(priv_protocol, usmNoPrivProtocol),
        )
        self._context = ContextData()
        # Serialise all SNMP operations — the shared SnmpEngine is not safe for
        # concurrent use.  Without this lock a coordinator poll (8 sequential GETs)
        # racing with a SET corrupts the engine's request-id tracking and one or
        # both operations silently receive no response.
        self._lock = asyncio.Lock()

    async def _transport(self) -> UdpTransportTarget:
        """Create a transport target — pysnmp 7.x requires await UdpTransportTarget.create()."""
        transport = await UdpTransportTarget.create((self._host, self._port))
        transport.timeout = 5
        transport.retries = 2
        return transport

    def close(self) -> None:
        """Release the SNMP engine dispatcher (call on integration unload)."""
        # closeDispatcher() was removed in pysnmp 7.x — guard for compatibility
        if hasattr(self._engine, "closeDispatcher"):
            self._engine.closeDispatcher()

    async def get_outlet_state(self, outlet: int) -> bool:
        """Return True if the outlet is on, False if off."""
        oid = f"{OID_OUTLET_STATUS}.{outlet}"
        _LOGGER.debug("GET %s (outlet %s)", oid, outlet)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine,
                self._auth,
                await self._transport(),
                self._context,
                ObjectType(ObjectIdentity(oid)),
            )
        if errorIndication:
            _LOGGER.error("GET outlet %s — errorIndication: %s", outlet, errorIndication)
            raise RuntimeError(f"SNMP error: {errorIndication}")
        if errorStatus:
            _LOGGER.error(
                "GET outlet %s — errorStatus: %s at index %s",
                outlet, errorStatus.prettyPrint(), errorIndex,
            )
            raise RuntimeError(
                f"SNMP error: {errorStatus.prettyPrint()} at index {errorIndex}"
            )
        for varBind in varBinds:
            oid_obj, val = varBind
            _LOGGER.debug(
                "GET outlet %s — OID: %s  value: %s  type: %s",
                outlet, oid_obj.prettyPrint(), val.prettyPrint(), type(val).__name__,
            )
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                raise RuntimeError(
                    f"OID {oid} returned {type(val).__name__} — "
                    "check the OID is correct for this PDU model and that the "
                    "SNMPv3 user has read access"
                )
            return int(val) == 1  # 1=on, 2=off
        return False

    async def get_outlet_name(self, outlet: int) -> str:
        """Return the outlet name configured on the PDU, or empty string if unavailable."""
        oid = f"{OID_OUTLET_NAME}.{outlet}"
        _LOGGER.debug("GET name %s (outlet %s)", oid, outlet)
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await get_cmd(
                self._engine,
                self._auth,
                await self._transport(),
                self._context,
                ObjectType(ObjectIdentity(oid)),
            )
        if errorIndication or errorStatus:
            _LOGGER.debug("Could not read name for outlet %s, using default", outlet)
            return ""
        for _, val in varBinds:
            _LOGGER.debug(
                "Name outlet %s — type: %s  value: %s",
                outlet, type(val).__name__, val.prettyPrint(),
            )
            if isinstance(val, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                _LOGGER.debug("Outlet %s has no name OID on this device", outlet)
                return ""
            # Only accept OctetString / DisplayString — if the PDU returns an
            # Integer here it means the name column is not supported or is
            # pointing at the wrong OID (e.g. returning the control value).
            if type(val).__name__ not in ("OctetString", "DisplayString"):
                _LOGGER.debug(
                    "Outlet %s name OID returned %s ('%s'), not a string — ignoring",
                    outlet, type(val).__name__, val.prettyPrint(),
                )
                return ""
            # asOctets() is the pyasn1-native way to get raw bytes from OctetString
            raw: bytes = val.asOctets() if hasattr(val, "asOctets") else bytes(val)
            return raw.rstrip(b"\x00").decode("ascii", errors="replace").strip()
        return ""

    async def get_outlet_names(self, count: int) -> dict[int, str]:
        """Return a dict of outlet_number -> name for all outlets."""
        return {
            outlet: await self.get_outlet_name(outlet)
            for outlet in range(1, count + 1)
        }

    async def get_all_outlet_states(self, count: int) -> dict[int, bool]:
        """Return a dict of outlet_number -> is_on for all outlets."""
        return {
            outlet: await self.get_outlet_state(outlet)
            for outlet in range(1, count + 1)
        }

    async def set_outlet(self, outlet: int, state: bool) -> None:
        """Send immediateOn or immediateOff to the specified outlet."""
        oid = f"{OID_OUTLET_CONTROL}.{outlet}"
        value = Integer32(CMD_IMMEDIATE_ON if state else CMD_IMMEDIATE_OFF)
        _LOGGER.debug("SET %s = %s (outlet %s -> %s)", oid, value, outlet, "on" if state else "off")
        async with self._lock:
            errorIndication, errorStatus, errorIndex, varBinds = await set_cmd(
                self._engine,
                self._auth,
                await self._transport(),
                self._context,
                ObjectType(ObjectIdentity(oid), value),
            )
        if errorIndication:
            _LOGGER.error("SET outlet %s — errorIndication: %s", outlet, errorIndication)
            raise RuntimeError(f"SNMP error: {errorIndication}")
        if errorStatus:
            _LOGGER.error(
                "SET outlet %s — errorStatus: %s at index %s",
                outlet, errorStatus.prettyPrint(), errorIndex,
            )
            raise RuntimeError(
                f"SNMP error: {errorStatus.prettyPrint()} at index {errorIndex}"
            )
        _LOGGER.debug("SET outlet %s -> %s OK", outlet, "on" if state else "off")
