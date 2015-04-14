#!/usr/bin/env python
import os

from troposphere import Ref, Template, Join, Base64, Parameter, FindInMap
from troposphere.openstack import nova
from troposphere import ec2

t = Template()
t.add_version()

os_name = t.add_parameter(Parameter(
    'OSName',
    Default='Ubuntu 14.04',
    Type='String',
    Description='Name of the base OS',
    AllowedValues=[u'Ubuntu 14.04', u'Ubuntu 14.10'],
))

t.add_mapping("OSNameToImageID",
              {u'Ubuntu 14.04': {
                  u'ID': u'd57696ba-5ed2-43fe-bf78-a587829973a9'},
               u'Ubuntu 14.10': {u'ID': u'na'}}
              )

vm_flavour = t.add_parameter(Parameter(
    'VMFlavour',
    Default='m1.small',
    Type='String',
    Description='VM flavour',
    AllowedValues=[
        u'm1.small',
        u'm1.medium',
        u'm1.large',
        u'm1.xlarge',
        u'm1.xxlarge'
    ],
))

availability_zone = t.add_parameter(Parameter(
    'AvailabilityZone',
    Default='monash-01',
    Type='String',
    Description='Availability zone',
    AllowedValues=[
        u'NCI',
        u'QRIScloud',
        u'intersect',
        u'intersect-01',
        u'melbourne',
        u'melbourne-np',
        u'melbourne-qh2',
        u'monash',
        u'monash-01',
        u'monash-02',
        u'pawsey',
        u'pawsey-01',
        u'sa',
        u'tasmania'
    ]
))

key_name = t.add_parameter(Parameter(
    'KeyPair',
    Description='OpenStack key pair name',
    Type='String',
))

mysql_root_password = t.add_parameter(Parameter(
    'MySQLRootPassword',
    Description='MySQL root password',
    Type='String',
))

mysql_rt_password = t.add_parameter(Parameter(
    'RTDatabaseUserPassword',
    Description='Database password for rt4 user',
    Type='String',
    Default='rt_pass'
))


# Copies a text file to the given location, optionally creating the directory
def inject_file(
        source,
        destination,
        create_dir=False,
        append=False,
        eof_delim='!!EOF!!'):
    with open(source) as f:
        content = f.read().splitlines()

    if append:
        f_redirect = '>>'
    else:
        f_redirect = '>'

    content = ['cat ' + f_redirect + ' ' + destination +
               ' << \'' + eof_delim + '\''] + content + [eof_delim]

    if (create_dir):
        path = os.path.dirname(destination)
        content = ['mkdir -p ' + path] + content

    return Join('\n', content)

# Define the instance security group, to allow:
#   - SSH
#   - SMTP (unencrypted and TLS)
#   - HTTPS
instance_sg = t.add_resource(
    ec2.SecurityGroup(
        'RTSecurityGroup',
        GroupDescription='Enable inbound SMTP, SSH and HTTP access',
        SecurityGroupIngress=[
            ec2.SecurityGroupRule(
                IpProtocol='tcp',
                FromPort='22',
                ToPort='22',
                CidrIp='0.0.0.0/0',
            ),
            ec2.SecurityGroupRule(
                IpProtocol='tcp',
                FromPort='443',
                ToPort='443',
                CidrIp='0.0.0.0/0',
            ),
            ec2.SecurityGroupRule(
                IpProtocol='tcp',
                FromPort='25',
                ToPort='25',
                CidrIp='0.0.0.0/0',
            ),
            ec2.SecurityGroupRule(
                IpProtocol='tcp',
                FromPort='465',
                ToPort='465',
                CidrIp='0.0.0.0/0',
            )]
    )
)

update_script = Join('\n', [
    'echo "Changing shell to bash for ec2-user"',
    'chsh -s /bin/bash ec2-user',
    'echo "Upgrade started at $(date)"',
    'apt-get update',
    'apt-get -y upgrade',
    'echo "Upgrade complete at $(date)"',
])

setup_volume_script = Join('\n', [
    'mkfs.ext4 /dev/vdc',
    'sed -ie \'s#/dev/vdb\t/mnt#/dev/vdb\t/tmp#\' /etc/fstab',
    'echo -e \'/dev/vdc\t/mnt/db_volume\tauto\tdefaults,nobootwait\t0\t2\' >> /etc/fstab',
    'umount /mnt',
    'mkdir /mnt/db_volume',
    'mount /tmp',
    'chmod 1777 /tmp',
    'mount /mnt/db_volume'
])

install_mysql_script = Join(
    '',
    [
        'echo "Installing and configuring mysql..."\n',
        'debconf-set-selections <<< \'mysql-server mysql-server/root_password password ', Ref(mysql_root_password), '\'\n',
        'debconf-set-selections <<< \'mysql-server mysql-server/root_password_again password ', Ref(mysql_root_password), '\'\n',
        'apt-get -y install mysql-server\n',
        'echo "Improving mysql security"\n',
        'echo "DELETE FROM mysql.user WHERE User=\'\';" | mysql --password=', Ref(mysql_root_password), '\n',
        'echo "DELETE FROM mysql.user WHERE User=\'root\' AND Host NOT IN (\'localhost\', \'127.0.0.1\', \'::1\');" | mysql --password=', Ref(mysql_root_password), '\n',
        'echo "FLUSH PRIVILEGES;" | mysql --password=', Ref(mysql_root_password), '\n',
    ])

relocate_mysql_data_dir_script = Join('\n',
                                      [
                                          'echo "Relocating the mysql data directory..."',
                                          '/etc/init.d/mysql stop',
                                          'mv /var/lib/mysql /mnt/db_volume',
                                          'ln -s /mnt/db_volume/mysql/ /var/lib/',
                                          inject_file('mysql-apparmor', '/etc/apparmor.d/local/usr.sbin.mysqld', append=True),
                                          '/etc/init.d/mysql start'
                                      ])

install_postfix_script = Join('\n', [
    'echo "Installing postfix..."',
    'debconf-set-selections <<< "postfix postfix/main_mailer_type select Internet with smarthost"',
    'debconf-set-selections <<< "postfix postfix/relayhost string smtp.monash.edu.au"',
    'debconf-set-selections <<< "postfix postfix/mailname string $VM_HOST"',
    'debconf-set-selections <<< "postfix postfix/destinations string localhost.localdomain, localhost, $VM_HOST"',
    'apt-get -y install postfix'
])

install_request_tracker_script = Join('\n', [
    'cd /tmp/',
    # Install RT4 dependencies
    Join(' ', [
        'apt-get -y install',
        'spawn-fcgi',
        'nginx',
        'ssl-cert',
        'libgd-gd2-perl',
        'libgraphviz-perl',
        'build-essential',
        'libapache-session-perl',
        'libcgi-emulate-psgi-perl',
        'libcgi-psgi-perl',
        'libconvert-color-perl',
        'libcrypt-eksblowfish-perl',
        'libcrypt-ssleay-perl',
        'libcrypt-x509-perl',
        'libcss-squish-perl',
        'libdata-guid-perl',
        'libdata-ical-perl',
        'libdate-extract-perl',
        'libdate-manip-perl',
        'libdatetime-perl',
        'libdatetime-format-natural-perl',
        'libdatetime-locale-perl',
        'libdbix-searchbuilder-perl',
        'libdevel-globaldestruction-perl',
        'libdevel-stacktrace-perl',
        'libemail-address-perl',
        'libemail-address-list-perl',
        'libfcgi-perl',
        'libfcgi-procmanager-perl',
        'libfile-sharedir-perl',
        'libfile-which-perl',
        'libgd-text-perl',
        'libgnupg-interface-perl',
        'libhtml-formattext-withlinks-perl',
        'libhtml-formattext-withlinks-andtables-perl',
        'libhtml-mason-perl',
        'libhtml-mason-psgihandler-perl',
        'libhtml-quoted-perl',
        'libhtml-rewriteattributes-perl',
        'libhtml-scrubber-perl',
        'libipc-run3-perl',
        'libjson-perl',
        'liblist-moreutils-perl',
        'liblocale-maketext-fuzzy-perl',
        'liblocale-maketext-lexicon-perl',
        'liblog-dispatch-perl',
        'libmime-types-perl',
        'libmodule-refresh-perl',
        'libmodule-versions-report-perl',
        'libnet-cidr-perl',
        'libnet-ssleay-perl',
        'libperlio-eol-perl',
        'libplack-perl',
        'libregexp-common-perl',
        'libregexp-common-net-cidr-perl',
        'libregexp-ipv6-perl',
        'librole-basic-perl',
        'libstring-shellquote-perl',
        'libsymbol-global-name-perl',
        'libtext-password-pronounceable-perl',
        'libtext-quoted-perl',
        'libtext-template-perl',
        'libtext-wikiformat-perl',
        'libtext-wrapper-perl',
        'libtime-modules-perl',
        'libtree-simple-perl',
        'libuniversal-require-perl',
        'libxml-rss-perl',
        'libmime-tools-perl',
        'libparallel-prefork-perl',
        'libnet-address-ip-local-perl'
    ]),
    # Build RT4
    'wget --quiet https://download.bestpractical.com/pub/rt/release/rt-4.2.10.tar.gz',
    'tar -zxf rt-4.2.10.tar.gz',
    'rm rt-4.2.10.tar.gz',
    'cd rt-4.2.10',
    Join('', ['./configure --with-db-rt-pass=\'', Ref(mysql_rt_password), '\''
              ' --with-web-user=www-data',
              ' --with-web-group=www-data',
              ' --enable-graphviz',
              ' --enable-gd'
              ]),
    # Configure CPAN
    'echo "Configuring cpan..."',
    '(echo yes; echo yes;) | su -c \'/usr/bin/perl -MCPAN -e shell\'',
    'su -c \'make fixdeps\'',
    'make install',
    Join(
        '', [
            'echo ', Ref(mysql_root_password), ' | make initialize-database']),
    # Remove RT4 install files
    'cd .. && rm -fR rt-4.2.10*',
    # Create a log directory
    'mkdir /var/log/rt4 && chown www-data:root $_ && chmod 770 $_',
    # Configure nginx
    inject_file('nginx-config.conf', '/etc/nginx/sites-available/default'),
    # Create Ubuntu RT4 upstart script
    inject_file('rt4-upstart.conf', '/etc/init/rt4.conf'),
    # Configure RT (RT_SiteConfig.pm)
    inject_file('rt-siteconfig.pm', '/opt/rt4/etc/RT_SiteConfig.pm'),
    # Set up RT4 cron jobs
    inject_file('rt-cron', '/etc/cron.d/rt'),
    # Add rt email aliases and rebuild aliases.db
    inject_file('rt-aliases', '/etc/aliases', append=True),
    'newaliases',
    # Start RT
    'service rt4 start',
    'service nginx restart'
])

postfix_lockdown_script = Join('\n', [
    'echo "Locking down postfix..."',
    inject_file('postfix-allowed-senders', '/etc/postfix/sender_filter'),
    inject_file('postfix-allowed-senders.cf', '/etc/postfix/main.cf', append=True),
    'cd /etc/postfix/ && postmap hash:sender_filter',
    'service postfix reload'
])

rt_next_steps = Join('\n', [
    'cat > /opt/rt4/next-steps << END',
    'Get a real SSL cert for $VM_HOST and reconfigure nginx',
    'Forward RT emails to rt@$VM_HOST',
    'END'
])

rt_setup_scripts = Base64(
    Join('\n', [
        '#!/bin/bash',
        'VM_HOST=`nslookup $(ifconfig eth0 | grep \'inet addr:\' | cut -d: -f2 | awk \'{print $1}\') | grep \'name =\' | cut -d \' \' -f 3 | sed \'s/.$//\'`',
        setup_volume_script,
        update_script,
        install_mysql_script,
        relocate_mysql_data_dir_script,
        install_postfix_script,
        install_request_tracker_script,
        postfix_lockdown_script,
        rt_next_steps
    ])
)

rt_block_device = t.add_resource(
    ec2.Volume('RTDatabase',
        AvailabilityZone=Ref(availability_zone),
        Size='40'
    )
)

instance = t.add_resource(nova.Server(
    'RTServer',
    image=FindInMap('OSNameToImageID', Ref(os_name), 'ID'),
    flavor=Ref(vm_flavour),
    availability_zone=Ref(availability_zone),
    key_name=Ref(key_name),
    security_groups=[Ref(instance_sg)],
    networks=[],
    block_device_mapping=[
        nova.BlockDeviceMapping(
            volume_id=Ref(rt_block_device),
            device_name='/dev/vdc'
        )
    ],
    user_data=rt_setup_scripts
))

print(t.to_json())
