# d3v-linux

Update the firmware on ADAM Audio D3V speakers from Linux. This tool downloads
ADAM's official Windows updater, extracts the firmware without running the
installer, and sends it to the speakers over USB HID. Wine and Windows are not
needed.

This is an independent project, not an ADAM Audio product. Firmware updates
write to the speakers' flash memory: keep USB and power connected during the
transfer. The repository contains no vendor firmware or installer binaries.

**This code is the result of AI-driven reverse engineering of the official ADAM
Audio updaters. Use at your own risk.**

## Install

You need Linux, Python 3.10 or newer, and 7-Zip (`7zz`, `7z`, or `7za`) with
NSIS support. 7-Zip is used only to unpack the official installer. The updater
itself has no third-party Python dependencies.

From a checkout of this repository:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
source .venv/bin/activate
d3v --help
```

Use your distribution's 7-Zip package. If it is installed elsewhere, pass its
path with `d3v download 1.7 --sevenzip /path/to/7zz`.

## Update the speakers

### 1. Download the firmware

```sh
d3v releases
d3v download 1.7
```

The ZIP, installer, and extracted firmware must all match the sizes and SHA-256
hashes in the release catalog. A changed upstream download is rejected. This
command does not access the speakers.

Firmware is cached under `$XDG_CACHE_HOME/d3v-linux`, or `~/.cache/d3v-linux`
when that variable is unset. Once downloaded, flashing works offline. You can
also supply a ZIP you downloaded from the [official D3V
page](https://downloads.adam-audio.com/adam-audio/desktop/d3v):

```sh
d3v download 1.7 --archive /path/to/official-updater.zip
```

### 2. Select the connected D3V

Connect the powered speakers by USB in normal audio mode, then run:

```sh
d3v devices
d3v prepare
```

`prepare` identifies the D3V and remembers its USB port. Keep the same cable and
port for the rest of the update. If several D3Vs are connected, use the port
shown by `devices`, for example `d3v prepare --port 3-2`.

This step matters because the bootloader uses a generic Nuvoton USB identity
that is also used by other devices. The updater only accepts a bootloader at the
previously selected speaker's port, with the expected HID descriptor.

### 3. Enter update mode

Leave USB connected. Disconnect the speakers' mains power, hold the front volume
knob, and reconnect mains power while holding it. Release the knob when the LED
pulses purple.

```sh
d3v devices
```

Note the bootloader's `/dev/hidrawN` path. If your user cannot open it, grant
temporary access to that specific node. Replace `/dev/hidrawN` below with the
path you just saw:

```sh
sudo setfacl -m "u:$(id -un):rw" /dev/hidrawN
```

`setfacl` is provided by the `acl` package on many distributions. The permission
disappears when the device disconnects. Run the updater as your normal user;
there is no need to run the downloaded installer or the entire tool as root.

### 4. Install the selected release

```sh
d3v flash 1.7
```

Review the version and USB port, then confirm. The updater checks every packet's
acknowledgment, checksum, and sequence number. It stops on a mismatch or timeout
and does not automatically retry. Transfer logs are saved in the cache's `logs/`
directory.

The tool cannot read the currently installed firmware version. Choose the
release deliberately; it does not prevent reinstalling or downgrading.

### 5. Reconnect and check audio

After the tool reports completion, wait for the LED to leave purple update mode.
ADAM describes three green flashes on successful installation. On the tested
pair, the speaker returned to normal operation but Linux retained the bootloader
USB interface until a full reconnect.

Disconnect both USB and mains power for five seconds. Reconnect them **without
holding the knob**, then run:

```sh
d3v devices
```

You should see `D3V audio`. A steady green LED selects analog input; press the
knob twice to select USB, indicated by cyan. These LED states and the
update-mode sequence are documented in the [ADAM D3V
manual](https://www.adam-audio.com/content/uploads/2025/05/adam-audio-d3v-desktop-monitor-user-manual-english.pdf).

## If something goes wrong

- **Hash mismatch:** the download is damaged or ADAM has replaced the upstream
  package. Do not bypass the check. Use the matching original ZIP or update the
  catalog after reviewing the new package.
- **No bootloader at the selected port:** keep the original USB connection and
  enter purple update mode. If you moved the cable, return to normal mode and
  run `prepare` again.
- **Packet counter mismatch at the first handshake:** re-enter update mode and
  grant access to the new HID node. The bootloader advances its counter even
  after a handshake with no firmware data, so each attempt needs a fresh
  session.
- **Transfer stopped partway through:** retain the log and check the connection.
  Do not assume the old firmware is intact. Re-enter update mode before making
  another complete attempt; the tool does not support resuming a partial write.
- **Still listed as a bootloader after completion:** perform the full USB and
  mains reconnect in step 5.

`devices`, `prepare`, `releases`, `download`, and `verify` never send HID
reports. Only `flash` communicates with the bootloader. There is deliberately no
separate probe command to consume the first handshake before an update.

## Development

See [the protocol notes](docs/protocol.md) for the reverse-engineering results.
The MIT license covers this project's code. Vendor firmware remains separate and
is obtained directly from ADAM's download service.
