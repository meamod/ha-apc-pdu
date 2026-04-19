# APC PDU — Home Assistant Integration

Control APC Switched Rack PDU outlets from Home Assistant over SNMPv3.

Tested on: **AP7920** (8-outlet Switched Rack PDU)  
Should also work on other APC sPDU-series devices that use the PowerNet MIB `1.3.6.1.4.1.318.1.1.4` OID tree.

---

## Features

- On/Off control per outlet as HA **Switch** entities
- Reads outlet names configured on the PDU (falls back to "Outlet N" if blank)
- Supports **multiple PDUs** — each is a separate config entry with its own device
- Configurable poll interval (default 10 s, minimum 5 s)
- Full SNMPv3 support: MD5/SHA/SHA-224/256/384/512 auth, DES/AES-128/192/256 privacy
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
   - Read **and** Write access (write is needed for outlet control)
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
| PDU Name | Friendly name shown in HA | `APC PDU` |
| IP Address / Hostname | Network address of the PDU | — |
| SNMP Port | UDP port for SNMP | `161` |
| SNMPv3 Username | Username configured on the PDU | — |
| Authentication Protocol | `none` / `MD5` / `SHA` / `SHA-224` / `SHA-256` / `SHA-384` / `SHA-512` | `SHA` |
| Authentication Password | Auth key (leave blank if auth protocol is `none`) | — |
| Privacy Protocol | `none` / `DES` / `AES-128` / `AES-192` / `AES-256` | `AES-128` |
| Privacy Password | Privacy key (leave blank if privacy protocol is `none`) | — |
| Number of Outlets | How many outlets to create switch entities for | `8` |
| Poll Interval (seconds) | How often to poll the PDU for state changes | `10` |

HA validates the connection (reads outlet 1) before saving. If validation fails, check the error log (see [Logging](#logging) below).

### Adding multiple PDUs

Repeat **Add Integration** for each PDU. Each gets its own device entry and independently configured credentials and poll interval.

---

## Options (editing after setup)

To change the **poll interval** or **outlet count** on an already-configured PDU without removing and re-adding it:

1. Go to **Settings → Devices & Services**
2. Find the **APC PDU** integration card
3. Click **Configure** on the PDU you want to edit
4. Adjust **Number of Outlets** and/or **Poll Interval** and click **Submit**

The integration reloads automatically — no full HA restart needed.

---

## Entities

Each outlet becomes a `switch` entity:

- **Entity ID:** `switch.<pdu_name>_<outlet_name>`  
  e.g. `switch.server_rack_web_server_1`
- **Name:** Outlet name from the PDU if set, otherwise `Outlet N`
- **Device:** All outlets from the same PDU are grouped under one device

Outlet names are read from the PDU once at setup. If you rename an outlet on the PDU, reload the integration to pick up the change (**Settings → Devices & Services → APC PDU → ⋮ → Reload**).

---

## How quickly are PDU changes reflected?

The integration **polls** the PDU on the configured interval (default 10 seconds). Changes made from HA (toggle a switch) are reflected immediately — the integration sends the SNMP SET and then requests a refresh straight away.

Changes made directly on the PDU (via its web UI, physical button, or another SNMP manager) will be seen within one poll interval at most.

> **Note:** APC PDUs support SNMP traps (push notifications), which would give near-instant detection of external changes. Trap support is not included in this version of the integration.

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

**Successful connection validation (setup form submitted):**
```
DEBUG Validating connection to 172.16.25.2:161 as user 'snmpuser' (auth=SHA, priv=AES-128)
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1 (outlet 1)
DEBUG GET outlet 1 — OID: 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1  value: 1  type: Integer32
DEBUG Connection validated — outlet 1 state: on
```

**Polling outlet states:**
```
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.1 (outlet 1)
DEBUG GET outlet 1 — OID: ...  value: 1  type: Integer32
DEBUG GET 1.3.6.1.4.1.318.1.1.4.4.2.1.3.2 (outlet 2)
DEBUG GET outlet 2 — OID: ...  value: 2  type: Integer32
...
```

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
| `cannot_connect` in the UI | Any of the above | Check `home-assistant.log` for the specific SNMP error message |

---

## SNMP OIDs (AP7920)

The AP7920 uses a single OID for each outlet — the same OID is used for both reading current state and sending commands:

| Purpose | OID | Values |
|---|---|---|
| Read outlet state | `1.3.6.1.4.1.318.1.1.4.4.2.1.3.{n}` | `1` = on, `2` = off |
| Set outlet state | `1.3.6.1.4.1.318.1.1.4.4.2.1.3.{n}` | `1` = immediateOn, `2` = immediateOff, `3` = immediateReboot |
| Read outlet name | `1.3.6.1.4.1.318.1.1.4.4.2.1.4.{n}` | OctetString |

Where `{n}` is the 1-based outlet index (1–8 for the AP7920).

---

## Troubleshooting

**Config flow shows "Invalid handler" on first load**  
HA hasn't installed `pysnmp` yet. Do a full restart (not just a reload).

**All outlets show as unavailable after setup**  
The first poll failed. Check `home-assistant.log` for an SNMP error from the coordinator update.

**Outlet names not updating after renaming on the PDU**  
Names are fetched once at integration load. Go to **Settings → Devices & Services → APC PDU → ⋮ → Reload**.

**Integration disappears after HA restart**  
Ensure the `custom_components/apc_pdu/` folder is in the correct location inside your HA `config/` directory.
