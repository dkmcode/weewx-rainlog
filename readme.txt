rainlog - weewx extension that uploads rain data to rainlog.org

INSTALLATION
1) run the installer:
Run the setup command from the WEEWX_ROOT directory.

   setup.py install --extension weewx-rainlog.tar.gz

2) modify weewx.conf:

[StdRESTful]
    [[Rainlog]]
        username = Rainlog_Username
	password = Rainlog_Password

3) restart weewx

On linux

   sudo service weewx restart

or on systems using systemd

   sudo systemctl restart weewx


CONFIGURATION KEYS
username - Your username for rainlog.org (required)
password - Your password for rainlog.org (required)
lastpath - The path to the file containing the epoch of the last update.
           If the path begins with / it is absolute. If not, it is relative
           to WEEWX_ROOT. (Optional: defaults to  archive/rainlog.last)
