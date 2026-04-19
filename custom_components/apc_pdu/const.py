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
OID_OUTLET_STATUS  = "1.3.6.1.4.1.318.1.1.4.4.2.1.3"
OID_OUTLET_CONTROL = "1.3.6.1.4.1.318.1.1.4.4.2.1.3"
CMD_IMMEDIATE_ON = 1
CMD_IMMEDIATE_OFF = 2

AUTH_PROTOCOLS = ["none", "MD5", "SHA", "SHA-224", "SHA-256", "SHA-384", "SHA-512"]
PRIV_PROTOCOLS = ["none", "DES", "AES-128", "AES-192", "AES-256"]
