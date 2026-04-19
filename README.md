# APC PDU — Home Assistant Integration

Control APC Switched Rack PDU outlets from Home Assistant over SNMPv3, with live current monitoring and full device identity reporting.

Tested on: **AP7920** (8-outlet Switched Rack PDU)  
Should also work on other APC sPDU/rPDU-series devices that expose the PowerNet MIB `1.3.6.1.4.1.318` OID tree.

---

## Features

- **On/Off control** per outlet as HA Switch entities
- **Current draw** sensor (total PDU load in Amps)
- **Load status** sensor (Low Load / Normal / Near Overload / Overload)
- Outlet names pulled from the PDU (falls back to "Outlet N" if blank)
- PDU name auto-detected during setup from `rPDUIdentName` (can be overridden)
- Outlet count auto-detected from `rPDUIdentDeviceNumOutlets` (no manual entry needed)
- Device panel populated with model number, serial number, and firmware version from the PDU
- Diagnostic sensors for PDU Name, Manufacture Date, and Number of Outlets
- Supports **multiple PDUs** — each is a separate config entry with its own device
- Configurable poll interval (default 10 s, minimum 5 s)
- Full SNMPv3 support: MD5 / SHA / SHA-224 / SHA-256 / SHA-384 / SHA-512 auth; DES / AES-128 / AES-192 / AES-256 privacy
- Credentials and settings editable after setup via the **Options** flow

---

## Requirements

### Home Assistant
- Home Assistant 2024.1 or newer
- Python 3.12+

### On the PDU
Before adding the integration, create an SNMPv3 user on the PDU via its web interface:

1. Log in to the PDU web UI
2. Navigate to **Administration → Network → SNMPv3 Access Control**
3. Create a user with:
   - Read **and** Write access (write is required for outlet control)
   - Your chosen auth protocol (SHA recommended) and auth password
   - Your chosen privacy protocol (AES-128 recommended) and privacy password
4. Note the exact username, passwords, and protocols — they must match what you enter in HA

---

## Installation

1. Copy the `custom_components/apc_pdu/` folder into your HA configuration directory:
   ```
   config/
   └── custom_components/
       └── apc_pdu/
           ├── __init__.py
           ├── config_flow.py
           ├── const.py
           ├── coordinator.py
           ├── manifest.json
           ├── sensor.py
           ├── snmp.py
           ├── strings.json
           └── switch.py
   ```

2. Restart Home Assistant fully (required on first install so HA installs `pysnmp`).

3. Go to **Settings → Devices & Services → Add Integration** and search for **APC PDU**.

---

## Configuration

Fill in the setup form:

| Field | Description | Default |
|---|---|---|
| PDU Name | Friendly name shown in HA. Leave blank to use the name configured on the PDU. | *(auto-detected)* |
| IP Address / Hostname | Network address of the PDU | — |
| SNMP Port | UDP port for SNMP | `161` |
| SNMPv3 Username | Username configured on the PDU | — |
| Authentication Protocol | `none` / `MD5` / `SHA` / `SHA-224` / `SHA-256` / `SHA-384` / `SHA-512` | `SHA` |
| Authentication Password | Required when Auth Protocol is not `none` | — |
| Privacy Protocol | `none` / `DES` / `AES-128` / `AES-192` / `AES-256` | `AES-128` |
| Privacy Password | Required when Privacy Protocol is not `none` | — |
| Poll Interval (seconds) | How often to poll the PDU for state changes | `10` |

> **Outlet count is auto-detected** from the PDU during setup — there is no outlet count field on the setup form. If auto-detection fails (the OID is not supported on your firmware), it falls back to 8. You can override it in the Options flow after setup.

HA validates the connection by reading outlet 1 before saving. If validation fails, check the error log (see [Logging](#logging) below).

### Adding multiple PDUs

Repeat **Add Integration** for each PDU. Each gets its own device entry and independently configured credentials and poll interval.

---

## Options (editing after setup)

To adjust settings on an already-configured PDU without removing and re-adding it:

1. Go to **Settings → Devices & Services**
2. Find the **APC PDU** integration card
3. Click **Configure** on the PDU you want to edit

| Option | Description | Default |
|---|---|---|
| Number of Outlets | Override the auto-detected outlet count. Set to `0` to use auto-detection. | `0` |
| Poll Interval (seconds) | How often to poll the PDU (5–300 s) | `10` |

The integration reloads automatically when you save — no full HA restart needed.

---

## Entities

### Switches

One switch entity per outlet:

| Attribute | Value |
|---|---|
| Entity ID | `switch.<pdu_name>_<outlet_name>` |
| Name | Outlet name from the PDU, or `Outlet N` if blank |
| Icon | `mdi:power-socket` |

All outlets from the same PDU are grouped under one device entry.

Outlet names are read from the PDU once at integration load. If you rename an outlet on the PDU, reload the integration to pick up the change (**Settings → Devices & Services → APC PDU → ⋮ → Reload**).

### Sensors

Two live-polling sensors per PDU:

| Entity | Device Class | Unit | Description |
|---|---|---|---|
| Current | `current` | A | Total PDU load in Amps, polled every scan interval |
| Load Status | `enum` | — | `Low Load` / `Normal` / `Near Overload` / `Overload` |

Three diagnostic sensors per PDU (visible in the entity list, hidden from dashboards by default):

| Entity | Description |
|---|---|
| PDU Name | The name configured on the PDU itself (`rPDUIdentName`) |
| Manufacture Date | Date of manufacture from the PDU (`rPDUIdentDateOfManufacture`) |
| Number of Outlets | Outlet count reported by the PDU (`rPDUIdentDeviceNumOutlets`) |

### Device panel

The HA device panel for each PDU is automatically populated with:

| Field | Source |
|---|---|
| Manufacturer | APC by Schneider Electric *(static)* |
| Model | `rPDUIdentModelNumber` |
| Serial Number | `rPDUIdentSerialNumber` |
| Firmware | `rPDUIdentFirmwareRev` |

---

## How quickly are PDU changes reflected?

The integration **polls** the PDU on the configured interval (default 10 seconds).

- **Changes made from HA** (toggling a switch) are reflected immediately via an optimistic state update — the UI updates at once without waiting for the next poll.
- **Changes made directly on the PDU** (via its web UI, physical button, or another SNMP manager) will be seen within one poll interval.

> **Note:** APC PDUs support SNMP traps (push notifications), which would give near-instant detection of external changes. Trap support is not included in this version.

---

## Logging

### Enable debug logging

Add the following to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.apc_pdu: debug
```

Restart HA (or reload the logger configuration) to apply.

### What the logs show

**Connection validation (setup form submitted):**
```
DEBUG Validating connection to 172.16.25.2:161 as user 'snmpuser' (auth=SHA, priv=AES-128)
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1 (outlet 1)
DEBUG GET outlet 1 — OID: 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1  value: 1  type: Integer32
DEBUG Connection validated — outlet 1 state: on
DEBUG PDU name from device: 'Server Rack PDU'
```

**Auto-detecting outlet count at startup:**
```
DEBUG Auto-detected 8 outlets from PDU
```

**Polling outlet states:**
```
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1 (outlet 1)
DEBUG GET outlet 1 — OID: ...  value: 1  type: Integer32
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.2 (outlet 2)
DEBUG GET outlet 2 — OID: ...  value: 2  type: Integer32
...
```

**Polling current draw:**
```
DEBUG GET 1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1
DEBUG GET 1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1 — type: Integer32  value: 23
```
*(value 23 = 2.3 A)*

**Switching an outlet on/off:**
```
DEBUG SET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.3 = 1 (outlet 3 -> on)
DEBUG SET outlet 3 -> on OK
```

### Common errors and fixes

| Error in log | Likely cause | Fix |
|---|---|---|
| `No SNMP response received` | Wrong IP/port, firewall blocking UDP 161, or PDU unreachable | Check network connectivity and that SNMP is enabled on the PDU |
| `unknownUserName` | SNMPv3 username doesn't exist on the PDU | Create the user in the PDU web UI; check for typos |
| `wrongDigest` / `usmStatsWrongDigests` | Auth password is wrong | Re-check the auth password |
| `decryptionError` / `usmStatsDecryptionErrors` | Privacy password is wrong | Re-check the privacy password |
| `NoSuchInstance` on outlet OID | Wrong OID for this PDU model, or SNMPv3 user lacks read permission | Verify the user has Read+Write access in the PDU's SNMP ACL |
| Current / Load Status sensors unavailable | `rPDU2PhaseStatus` OIDs not supported on this firmware | Check debug log for the load OIDs; override may be needed in `const.py` |
| `cannot_connect` in the UI | Any of the above | Check `home-assistant.log` for the specific SNMP error |

---

## SNMP OIDs (AP7920)

### Outlet control

The AP7920 uses a **single OID** per outlet for both reading state and sending commands:

| Purpose | OID | Values |
|---|---|---|
| Read / set outlet state | `1.3.6.1.4.1.318.1.1.4.4.2.1.3.{n}` | Read: `1`=on, `2`=off · Write: `1`=immediateOn, `2`=immediateOff, `3`=immediateReboot |
| Read outlet name | `1.3.6.1.4.1.318.1.1.4.4.2.1.4.{n}` | OctetString |

Where `{n}` is the 1-based outlet index (1–8 for the AP7920).

### Load monitoring

| Purpose | OID | Values |
|---|---|---|
| Total current draw | `1.3.6.1.4.1.318.1.1.12.2.3.1.1.2.1` | Integer, tenths of Amps (e.g. `23` = 2.3 A) |
| Load state | `1.3.6.1.4.1.318.1.1.12.2.3.1.1.3.1` | `1`=Low Load, `2`=Normal, `3`=Near Overload, `4`=Overload |

### Device identity (scalar, all use `.0` instance suffix)

| Purpose | OID |
|---|---|
| PDU name | `1.3.6.1.4.1.318.1.1.12.1.1.0` |
| Firmware revision | `1.3.6.1.4.1.318.1.1.12.1.3.0` |
| Date of manufacture | `1.3.6.1.4.1.318.1.1.12.1.4.0` |
| Model number | `1.3.6.1.4.1.318.1.1.12.1.5.0` |
| Serial number | `1.3.6.1.4.1.318.1.1.12.1.6.0` |
| Number of outlets | `1.3.6.1.4.1.318.1.1.12.1.8.0` |

---

## Troubleshooting

**Config flow shows "Invalid handler" on first load**  
HA hasn't installed `pysnmp` yet. Do a full restart (not just a reload).

**All outlets show as unavailable after setup**  
The first poll failed. Check `home-assistant.log` for an SNMP error from the coordinator update.

**Outlet count is wrong after setup**  
The `rPDUIdentDeviceNumOutlets` OID may return a different value on your firmware, or may not be supported. Go to **Settings → Devices & Services → APC PDU → Configure** and set the **Number of Outlets** override to the correct value.

**Current / Load Status sensors are permanently unavailable**  
The `rPDU2PhaseStatus` OIDs (`1.3.6.1.4.1.318.1.1.12.2.3.x`) are not supported on all firmware versions. Enable debug logging and look for the GET result for those OIDs to confirm. The outlet switches are unaffected.

**Outlet names not updating after renaming on the PDU**  
Names are fetched once at integration load. Go to **Settings → Devices & Services → APC PDU → ⋮ → Reload**.

**Integration disappears after HA restart**  
Ensure the `custom_components/apc_pdu/` folder is in the correct location inside your HA `config/` directory.

---

## Notes for other APC PDU models

The OIDs in this integration were confirmed on an **AP7920**. Other models may use different OIDs or return values in different formats. If you use this integration on a different model:

- Enable debug logging to see what each OID returns
- The outlet control/status OID (`1.3.6.1.4.1.318.1.1.4.4.2.1.3`) is common across the sPDU family
- The `rPDU2` branch (`1.3.6.1.4.1.318.1.1.12`) is used by newer firmware and rPDU2-series hardware; older firmware may use different branches
- The GitHub issue tracker is the best place to report confirmed OIDs for other models
