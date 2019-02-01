#!/bin/env python3
#
# Simple script to join or leave a realm.
#
# This script will also rewrite the Samba and SSSD conf files and restart Samba and SSSD
#
# Script should be safe as any exception or error during re-configuration should
#   result in restoring a backup copy of the previous config file
#

import os
import sh
import sys
import glob
import shutil
import logging
from configobj import ConfigObj
import time
import shlex, subprocess
import ldap3
import argparse
#import radium.utils.pwcrypt as pwcrypt

# create logger with 'spam_application'
logger = logging.getLogger('joinAD')
logger.setLevel(logging.DEBUG)
# create file handler which logs even debug messages
fh = logging.FileHandler('/var/log/joinAD.log')
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

class RealmException(Exception):
    pass

class ConfigSSSDException(Exception):
    pass

class ConfigSambaException(Exception):
    pass

def get_sid(upn, password, domain):
    # Get kerberos ticket using kinit
    sh.kinit(sh.echo(password),(upn))
    logger.info(sh.klist())

    server = ldap3.Server(host=domain, get_info=ldap3.ALL)
    conn = ldap3.Connection(server, user=upn, password=password,
                            auto_bind=True)

    search_base = ','.join(['DC=' + dp for dp in domain.split('.')])
    search_filter = '(&(objectclass=domain))'
    params = {
        'search_base': search_base,
        'search_filter': search_filter,
        'search_scope': ldap3.SUBTREE,
        'attributes': ['objectSid'],
        'paged_size': 1,
        'generator': False
    }

    conn.extend.standard.paged_search(**params)

    return conn.entries[0].objectSid


def get_netbios(upn, password, domain):
    server = ldap3.Server(host=domain, get_info=ldap3.ALL)
    conn = ldap3.Connection(server, user=upn, password=password,
                            auto_bind=True)

    domain_components = ','.join(['dc=' + dp for dp in domain.split('.')])
    search_filter = '(&(netbiosname=*))'

    params = {
        'search_base': 'CN=Partitions,CN=Configuration,' + domain_components,
        'search_filter': search_filter,
        'search_scope': ldap3.SUBTREE,
        'attributes': ldap3.ALL_ATTRIBUTES,
        'paged_size': 1,
        'generator': False
    }

    results = conn.extend.standard.paged_search(**params)

    for info in results:
        if info['attributes']['nCName'].lower() == domain_components:
            return info['attributes']['nETBIOSName']

def create_samba_default_config(smbcfgfile):
    # Setup the Samba confguration file
    cfg = ConfigObj()
    cfg.filename = smbcfgfile
    cfg['global'] = {}
    cfg['global']['workgroup'] = 'StrongLink'
    cfg['global']['server string'] = 'StrongLink Samba Server'
    cfg['global']['log file'] = '/var/log/samba/log.%m'
    cfg['global']['log level'] = '3'
    cfg['global']['max log size'] = '50'
    cfg['global']['security'] = 'user'
    cfg['global']['client signing'] = 'auto'
    cfg['global']['server signing'] = 'auto'
    cfg['global']['load printers'] = 'no'
    cfg['global']['printing'] = 'bsd'
    cfg['global']['printcap name'] = '/dev/null'
    cfg['global']['disable spoolss'] = 'yes'
    cfg.write()

def configure_samba(upn, password, domain, reset=False):
    backup_complete = False
    smbcfgfile = '/etc/samba/smb.conf'
    # Make a backup of the Samba config file
    if not os.path.isfile(smbcfgfile):
        # If there is no existing / default smb.conf file, first create one
        #   so that we can both keep a backup and be able to restore if config fails
        create_samba_default_config(smbcfgfile + '.bak')
    else:
        shutil.copy(smbcfgfile, smbcfgfile + '.bak')
    backup_complete = True

    try:
        if not reset:
            # get AD workgroup
            workgroup = get_netbios(upn, password, domain)

            # Setup the Samba confguration file
            cfg = ConfigObj()
            cfg.filename = smbcfgfile

            cfg['global'] = {}
            cfg['global']['workgroup'] = workgroup.lower() if workgroup else ''
            cfg['global']['server string'] = 'StrongLink Samba Server'
            cfg['global']['log file'] = '/var/log/samba/log.%m'
            cfg['global']['log level'] = '3'
            cfg['global']['max log size'] = '50'
            cfg['global']['security'] = 'ads'
            cfg['global']['encrypt passwords'] = 'yes'
            cfg['global']['passdb backend'] = 'tdbsam'
            cfg['global']['kerberos method'] = 'secrets and keytab'
            cfg['global']['realm'] = domain.lower()
            cfg['global']['vfs objects'] = 'acl_xattr'
            cfg['global']['map acl inherit'] = 'yes'
            cfg['global']['store dos attributes'] = 'yes'
            cfg['global']['deadtime'] = '10'
            cfg['global']['client signing'] = 'auto'
            cfg['global']['server signing'] = 'auto'
            cfg['global']['dns proxy'] = 'no'
            cfg['global']['load printers'] = 'no'
            cfg['global']['printing'] = 'bsd'
            cfg['global']['printcap name'] = '/dev/null'
            cfg['global']['disable spoolss'] = 'yes'
            cfg['global']['map untrusted to domain'] = 'yes'

            cfg.write()
        # When removing a domain, rewrite the default StrongLink samba config
        else:
            create_samba_default_config(smbcfgfile)

        # Reload SMB
        sh.systemctl('restart','smb')

    except Exception as exc:
        # Something nasty happened when we tried to reconfigure samba
        #   so we need to restore our last backup file
        logger.error("Error configuring Samba, restoring backup config: {}".format(str(exc)))
        if backup_complete:
            shutil.copy(smbcfgfile + '.bak', smbcfgfile)
            # Reload SMB
            sh.systemctl('restart','smb')
        raise ConfigSambaException

def create_default_sssd_config(sssdcfgfile):
    # Nothing to do here for default
    sssdcfg = ConfigObj(sssdcfgfile)
    sssdcfg.write()

def configure_sssd(upn, password, domain, reset=False):
    backup_complete = False
    sssdcfgfile = '/etc/sssd/sssd.conf'

    if not os.path.isfile(sssdcfgfile):
        # Create a default sssd.conf if one does not currently exist
        logger.info("Creating default SSSD config")
        create_default_sssd_config(sssdcfgfile + '.bak')
    else:
        # Make a backup of the sssd config file
        logger.info("Backing up SSSD config")
        shutil.copy(sssdcfgfile, sssdcfgfile + '.bak')
    backup_complete = True

    try:
        # Stop SSSD and clear caches
        logger.info("Stoping sssd service and clearing caches")
        sh.systemctl('stop','sssd')
        for f in glob.glob('/var/lib/sss/db/*'):
            os.remove(f)

        if not reset:
            # get_sid
            sid = get_sid(upn, password, domain)
            logger.info("configure_sssd: Got sid: {}".format(str(sid)))
            # Edit the sssd.conf with IdMap Details
            sssdcfg = ConfigObj(sssdcfgfile)

            logger.info("Setting SSSD config for domain: {}".format(str(domain)))
            domain_key = 'domain/'+domain

            # Check to see if key passed in was correct case
            # If not, try to find a key that matches caseless

            if domain_key not in sssdcfg:
                matches = [k for k in sssdcfg if k.lower() == domain_key.lower()]
                if len(matches) > 1:
                    logger.error("Exact key match not found, but multiple similar keys: {} --- Using {}".format(str(matches), str(matches[0])))
                elif len(matches) == 1:
                    logger.info("Found good match for domain {} on sssd key {}".format(str(domain_key), str(matches[0])))
                else:
                    logger.error("Found NO good matches for domain {}".format(str(domain_key)))
                    raise Exception("No matching domain")
                domain_key = matches[0]

            sssdcfg[domain_key]['ldap_id_mapping'] = useIdMap
            if useIdMap:
                sssdcfg[domain_key]['ldap_idmap_range_min'] = 1000000
                sssdcfg[domain_key]['ldap_idmap_range_size'] = 2000000
                sssdcfg[domain_key]['ldap_idmap_default_domain_sid'] = sid
            else:
                sssdcfg[domain_key].pop('ldap_idmap_range_min', None)
                sssdcfg[domain_key].pop('ldap_idmap_range_size', None)
                sssdcfg[domain_key].pop('ldap_idmap_default_domain_sid', None)
        else:
            # Default sssd.conf would go here
            create_default_sssd_config(sssdcfgfile)

        sssdcfg.write()

        # Restart sssd
        sh.systemctl('restart', 'sssd')

    except Exception as exc:
        logger.error("Error configuring sssd, restoring backup config: {}".format(str(exc)))
        if backup_complete:
            # Something nasty happened when we tried to reconfigure sssd.conf
            #   so we need to restore our last backup file
            shutil.copy(sssdcfgfile + '.bak', sssdcfgfile)

            # Restart SSSD now that we've restored out backup
            sh.systemctl('restart', 'sssd')
        raise ConfigSSSDException

if __name__ == "__main__":

    try:
        parser = argparse.ArgumentParser(description='Join or leave AD')
        parser.add_argument('user', help='User name')
        parser.add_argument('password', help='User password')
        parser.add_argument('domain', help='Domain name')
        parser.add_argument('useIdMap', help='Use LDAP ID mapping?')

        # Optional arguments
        parser.add_argument('--leave', help='Leave domain', action='store_true')

        args = parser.parse_args()
        user = args.user
        password = args.password
        domain = args.domain

        if args.useIdMap.lower() in ('true', 't'):
            useIdMap = True
        elif args.useIdMap.lower() in ('false', 'f'):
            useIdMap = False
        else:
            raise argparse.ArgumentTypeError('Boolean value expected')

        # True if we are leaving an AD instead of joining one
        leave_AD = args.leave
        upn=user+'@'+domain.upper()

        # If not root then switch to root user and re-run this script
        if os.geteuid() != 0:
            os.execvp('sudo', ['sudo', 'python3'] + sys.argv)

        logger.info('user = {}, password = {}, domain = {}'.format(user, 'XXXXXXXX', domain))

        # Decrypt password
        # password = pwcrypt.decrypt(password)

        if not leave_AD:
            logger.info("Joining realm...")
            # Make sure we're not already joined to the domain
            output = sh.realm('list')

            # Check for a case mismatch before joining
            domain_output = ''
            for line in output:
                if 'domain-name' not in line:
                    continue
                domain_output = line.split()[-1]

            if domain.lower() == domain_output.lower():
                logger.info('Already joined to {}'.format(domain))
                sys.exit(0)

            # Join the AD domain
            try:
                sh.realm(sh.echo(password), 'join', '-v', '--user=' + user, domain)
            except Exception as exc:
                raise RealmException("Unable to join realm for  domain: {} user: {}".format(str(domain), str(user)))

        else:
            logger.info("Leaving realm...")
            try:
                sh.realm(sh.echo(password), 'leave', '-v', '--user=' + user, domain)
            except Exception as exc:
                raise RealmException("Unable to leave realm for  domain: {} user: {}".format(str(domain), str(user)))

        logger.info(sh.realm('list'))

        # Write or reset sssd.conf file and restart SSSD
        logger.info("Configuring SSSD")
        configure_sssd(upn, password, domain, reset=leave_AD)

        # Write or reset smb.conf file and restart Samba
        logger.info("Configuring Samba")
        configure_samba(upn, password, domain, reset=leave_AD)

    except RealmException as exc:
        logger.error(str(exc))
        sys.exit(1)
    except ConfigSSSDException as exc:
        logger.error("Error configuring SSSD: {}".format(str(exc)))
        sys.exit(1)
    except ConfigSambaException as exc:
        logger.error("Error configuring Samba: {}".format(str(exc)))
        sys.exit(1)
    except Exception as exc:
        logger.error("*** Unhandled exception *** : {}".format(str(exc)))
        sys.exit(1)

    sys.exit(0)
