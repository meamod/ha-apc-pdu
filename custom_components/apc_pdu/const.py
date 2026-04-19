DOMAIN = "apc_pdu"

CONF_SNMP_USERNAME = "snmp_username"
CONF_AUTH_PROTOCOL = "auth_protocol"
CONF_AUTH_KEY = "auth_key"
CONF_PRIV_PROTOCOL = "priv_protocol"
CONF_PRIV_KEY = "priv_key"
CONF_OUTLET_COUNT = "outlet_count"

CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_PORT = 161
DEFAULT_OUTLET_COUNT = 8
DEFAULT_SCAN_INTERVAL = 10
MIN_SCAN_INTERVAL = 5

# AP7920 (sPDU / Switched Rack PDU) exposes a single OID for each outlet:
# sPDUOutletControlOutletCommand — 1.3.6.1.4.1.318.1.1.4.4.2.1.3.{n}
# Reading returns current state: 1=on, 2=off
# Writing sends a command:       1=immediateOn, 2=immediateOff, 3=immediateReboot
# There is no separate status table on this model (.4.2 is sPDUMasterControl, not outlets).
OID_OUTLET_NAME    = "1.3.6.1.4.1.318.1.1.4.4.2.1.4"  # sPDUOutletControlName (OctetString) — AP7920 uses column 4, not 2
# sPDUOutletControlOutletCommand — same OID for both reading state and sending commands
OID_OUTLET_CONTROL = "1.3.6.1.4.1.318.1.1.4.4.2.1.3"
CMD_IMMEDIATE_ON = 1
CMD_IMMEDIATE_OFF = 2

# rPDU2 load metrics — confirmed on AP7920
# rPDU2PhaseStatusCurrent (.1.1.2.1) — Integer, tenths of Amps; divide by 10 for Amps
# rPDU2PhaseStatusLoadState (.1.1.3.1) — 1=lowLoad 2=normal 3=nearOverload 4=overload
OID_LOAD_AMPS  = "1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1"
OID_LOAD_STATE = "1.3.6.1.4.1.318.1.1.12.2.3.1.1.3.1"

# rPDU identity scalars (all use .0 instance suffix)
OID_IDENT_NAME             = "1.3.6.1.4.1.318.1.1.12.1.1.0"
OID_IDENT_MODEL            = "1.3.6.1.4.1.318.1.1.12.1.5.0"
OID_IDENT_SERIAL           = "1.3.6.1.4.1.318.1.1.12.1.6.0"
OID_IDENT_FIRMWARE         = "1.3.6.1.4.1.318.1.1.12.1.3.0"
OID_IDENT_DATE_OF_MANUFACTURE = "1.3.6.1.4.1.318.1.1.12.1.4.0"
OID_IDENT_NUM_OUTLETS      = "1.3.6.1.4.1.318.1.1.12.1.8.0"

LOAD_STATE_MAP = {
    1: "Low Load",
    2: "Normal",
    3: "Near Overload",
    4: "Overload",
}

AUTH_PROTOCOLS = ["none", "MD5", "SHA", "SHA-224", "SHA-256", "SHA-384", "SHA-512"]
PRIV_PROTOCOLS = ["none", "DES", "AES-128", "AES-192", "AES-256"]
