# OrchestratorSiphon

In order to protect your Orchestrator keystore file from being compromised, it's vital that no one else ever gets access to it. 

This program provides easy access to just about any action that requires the original Orchestrator keystore. This way you can keep it unlinked from hot wallets and only store the keystore on 1 very secure machine and some (encrypted) backups.

> ⚠️ Do not trust anyone with access to your keystore, not even this script! Please take a look through the python source files to verify what the program does. You can search for `source_private_key` to find all locations where the key is accessed. In case of doubts, stick to the official `go-livepeer` binaries.

## Get started
Clone repo to your machine: ```git clone https://github.com/stronk-dev/OrchestratorSiphon.git```

Make sure to modify the config to : ```nano OrchestratorSiphon/config.ini```

> ℹ️ You can also pass any config variable as an environment variable instead. These always take precedence over whatever is in the config.
> You can set an environment variable with `export CONFIGOPTION='VALUE'` on Linux and `set CONFIGOPTION=VALUE` on Windows. The config file shows the names of all corresponding environment variables.

Dependencies:

```
pip install web3
pip install eth-utils
pip install setuptools
```

Run the script manually to test if it works:
```
python3 OrchestratorSiphon/OrchestratorSiphon.py
```

## Run in screen
If you don't want to store the password to your keystore next tot the keystore file itself, the recommend way to running the script is something like `screen`. This allows you to set the password field empty in the config, type in the password when the script asks for it and then detach the terminal so it keeps running in the background.

Start a new `screen` session: ```screen -S orchSiphon```

Run the script: ```python3 OrchestratorSiphon/OrchestratorSiphon.py```

Now enter the password to the keystore file when asked. Then enter `0` to launch the siphon. Now you can de-attach the `screen` session with:  ```<Ctrl + A>, then press <d>```

> ⚠️ Although screen can in theory keep running indefinitely, if the process stops for any reason like a reboot of the system it will not come back up. So be sure to also enable Vires' [Telegram bot](https://github.com/0xVires/web3-livepeer-bot) to get notified if the node is not calling rewards.

You can list `screen` sessions which are running with ```screen -ls```. To re-attach use ```screen -r orchSiphon```

Now you can view the logs, enter [interactive mode](https://github.com/stronk-dev/OrchestratorSiphon?tab=readme-ov-file#interactive-mode) or exit the script as usual using `<CTRL + c>`

## Systemd script
Example systemd script (modify paths):
```sudo nano /etc/systemd/system/orchSiphon.service```

```
[Unit]
Description=LPT bond transfer
After=multi-user.target

[Service]
Type=simple
Restart=always
WorkingDirectory=/path/to/OrchestratorSiphon
ExecStart=/usr/bin/python3 -u /path/to/OrchestratorSiphon/OrchestratorSiphon.py

[Install]
WantedBy=multi-user.target
```

Save service file and enable the service:

```
systemctl daemon-reload
systemctl enable --now orchSiphon.service
```

Check logs: ```journalctl -u orchSiphon.service -n 500 -f```

## Arch Linux (or other venv)

For operatins systems like Arch linux, enter the repository and create a new virtual environment:

```
cd OrchestratorSiphon
python -m venv .
```

Install depedencies:
```
bin/pip install web3
bin/pip install setuptools
bin/pip install eth-utils
```

Don't forget to use the python binary from the virtual environment when running the script: ```bin/python3 OrchestratorSiphon.py```

For the `systemd` script this means changing ExecStart to `ExecStart=/path/to/OrchestratorSiphon/bin/python3 -u /path/to/OrchestratorSiphon/OrchestratorSiphon.py`

# Interactive mode

If no password file is given, the script will ask the user to input the password to the keystore. You can also switch to interactive mode by sending a 'SIGQUIT' (`<CTRL + \>`) or 'SIGTSTP' (`<CTRL + z>`) signal to the script.

Interactive mode allows you to do more stuff, like voting on proposals or setting a new service URI.