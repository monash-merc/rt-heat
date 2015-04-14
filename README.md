# RT 4.2.10 Heat template

This repository contains files required to generate a Heat template to install a self-contained instance of RT 4.2.10. The json template is also provided as rt-template.json, but this can be customised and built using rt-template.py. The rt-template.py scripts depends on [troposphere](https://github.com/cloudtools/troposphere).

## List of files
* rt-template.json -> Heat template
* rt-template.py -> Heat template build script
* parameters.yaml -> Heat parameters file
* mysql-apparmor -> /etc/apparmor.d/local/usr.sbin.mysqld
* nginx-config.conf -> /etc/nginx/sites-available/default
* postfix-allowed-senders -> /etc/postfix/sender_filter
* postfix-allowed-senders.cf -> /etc/postfix/main.cf
* rt-aliases -> /etc/aliases
* rt-cron -> /etc/cron.d/rt
* rt-siteconfig.pm -> /opt/rt4/etc/RT_SiteConfig.pm
* rt4-upstart.conf -> /etc/init/rt4.conf