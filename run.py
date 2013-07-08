#!/usr/bin/env python

import argparse
import ConfigParser
import netaddr
import os
import paramiko
import string
import sys


TOPDIR = os.getcwd()
PUPPET_DIR = os.path.join(TOPDIR, "puppet")
TEMPLATE_DIR = os.path.join(PUPPET_DIR, "templates")
MANIFEST_DIR = os.path.join(PUPPET_DIR, "manifests")

CONFIG_FILE = ConfigParser.ConfigParser()
DEFAULT_CONFIG = dict()
NODE_CONFIG = dict()


def check_puppet_dirs():
    if not os.path.exists(TEMPLATE_DIR):
        print "%s don't exists" % TEMPLATE_DIR
        sys.exit(-1)
    if not os.path.exists(MANIFEST_DIR):
        print "%s don't exists" % MANIFEST_DIR
        sys.exit(-1)

def is_validate_ip_address(data):
    try:
        netaddr.IPAddress(data)
        return True
    except Exception:
        return False


def parse_config_file(config_file):
    global CONFIG_FILE
    global DEFAULT_CONFIG
    global NODE_CONFIG

    CONFIG_FILE.read(config_file)
    for conf in CONFIG_FILE.items("default"):
        DEFAULT_CONFIG[conf[0]] = conf[1]
    old_nodes = {}
    for section in CONFIG_FILE.sections():
        if section == 'default':
            continue
        old_nodes[section] = dict()
        for option in CONFIG_FILE.options(section):
            old_nodes[section][option] = CONFIG_FILE.get(section, option)
    NODE_CONFIG['old_nodes'] = old_nodes


def write_config_file(config_file):
    global CONFIG_FILE
    global NODE_CONFIG

    old_sections = CONFIG_FILE.sections()
    old_nodes = NODE_CONFIG['old_nodes']
    for fqdn in old_nodes.iterkeys():
        if fqdn not in old_sections:
            CONFIG_FILE.add_section(fqdn)
        for option in old_nodes[fqdn]:
            CONFIG_FILE.set(fqdn, option, old_nodes[fqdn][option])
    CONFIG_FILE.write(open(config_file, "w"))


def parse_cli_arguments():
    global DEFAULT_CONFIG
    global NODE_CONFIG

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config-file',
                        required=True,
                        help=('A file contains swift cluster config infos'),
                       )
    parser.add_argument('-a', '--add-nodes',
                        action='append',
                        required=True,
                        help=('Host to be added into the swift cluster'
                              'format is: <zone>:<ip>:<dev1,dev2>'),
                       )
    parser.add_argument('-r', '--role',
                        default='storage',
                        help=('The role of the new nodes.'),
                       )
    parser.add_argument('--username',
                        default=None,
                        help=('ssh username'),
                       )
    parser.add_argument('--password',
                        default=None,
                        help=('ssh password'),
                       )
    parser.add_argument('--proxy-pipeline',
                        default=['catch_errors', 'healthcheck', 'cache',
                                 'swift3', 'tempauth', 'proxy-server'],
                        help=('Swift pipeline'),
                       )
    parser.add_argument('--swift-local-net-ip',
                        default=None,
                        help=('Which network interface will used to by swift '
                              'to communicate with other storage nodes'),
                       )
    parser.add_argument('--remote-log-host',
                        default=None,
                        help=('Forward log to which remote host'),
                       )

    defaults = DEFAULT_CONFIG
    args = parser.parse_args()
    parse_config_file(args.config_file)
    new_nodes = {}
    for new_node in args.add_nodes:
        username = args.username or defaults.get('username')
        password = args.password or defaults.get('password')
        zone, ip, disks = new_node.split(':')
        if not zone or not ip or not disks:
            print 'Illegal argument: %s' % new_node
            sys.exit(-1)
        if not is_validate_ip_address(ip):
            print 'Illegal ip address: %s' % new_node
            sys.exit(-2)
        fqdn = get_node_fqdn(ip, username=username, password=password)
        if not fqdn:
            print 'Failed to get FQDN by ssh'
            sys.exit(-3)
        if fqdn in new_nodes.keys():
            old_ip = new_nodes[fqdn]['ip']
            print ("Different ip but the same fqdn,"
                   "the two ip is '%s' and '%s'") % (ip, old_ip)
            sys.exit(-4)
        else:
            new_nodes[fqdn] = dict()
        proxy_pipeline = args.proxy_pipeline or defaults.get('proxy_pipeline')
        local_net_ip = args.swift_local_net_ip or defaults.get('swift_local_net_ip')
        log_host = args.remote_log_host or defaults.get('remote_log_host')
        new_nodes[fqdn]['ip'] = ip
        new_nodes[fqdn]['proxy_pipeline'] = proxy_pipeline
        new_nodes[fqdn]['remote_log_host'] = log_host
        new_nodes[fqdn]['role'] = args.role
        new_nodes[fqdn]['swift_zone'] = zone
        new_nodes[fqdn]['swift_local_net_ip'] = local_net_ip
        new_nodes[fqdn]['storage_devices'] = disks.split(',')
    NODE_CONFIG['new_nodes'] = new_nodes
    return args.config_file


def ssh_execute(host, cmds):
    kwargs = {}
    kwargs['username'] = DEFAULT_CONFIG.get("ssh_username")
    kwargs['password'] = DEFAULT_CONFIG.get("ssh_password")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.load_system_host_keys()
    ssh.connect(host, **kwargs)
    transport = ssh.get_transport()
    for cmd in cmds:
        print "%s executing '%s'" % (host, cmd),
        session = transport.open_session()
        session.exec_command(cmd)
        if session.recv_exit_status():
            print "%20s" % "failed"
            return False
        else:
            print "%20s" % "success"
    ssh.close()
    return True


def get_node_fqdn(host, username=None, password=None):
    kwargs = {}
    kwargs['username'] = username
    kwargs['password'] = password
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.load_system_host_keys()
    ssh.connect(host, **kwargs)
    stdin, out, err = ssh.exec_command("hostname -f")
    fqdn = out.read()
    ssh.close()
    return string.strip(fqdn)


def generate_manifest_file(nodes, memcache_servers):
    global DEFAULT_CONFIG

    defaults = DEFAULT_CONFIG
    # read puppet storage node template
    with open(os.path.join(TEMPLATE_DIR, "node.pp")) as ifile:
        node_template = ifile.read()

    with open(os.path.join(MANIFEST_DIR, "site.pp"), "w") as ofile:
        local_net_ip = nodes[fqdn]['swift_local_net_ip'] or defaults.get('swift_local_net_ip')
        log_host = nodes[fqdn]['remote_log_host'] or defaults.get('remote_log_host')
        for fqdn in nodes.iterkeys():
            node_conf = {}
            node_conf['node_fqdn'] = fqdn
            node_conf['memcache_servers'] = memcache_servers
            node_conf['remote_log_host'] = log_host
            node_conf['swift_zone'] = nodes[fqdn]['swift_zone']
            node_conf['swift_local_net_ip'] = local_net_ip
            node_conf['storage_devices'] = nodes[fqdn]['storage_devices']
            ofile.write(node_template % node_conf)


def main():
    # check all necessary directory
    check_puppet_dirs()

    # parse cli arguments
    config_file = parse_cli_arguments()

    old_nodes = NODE_CONFIG['old_nodes']
    new_nodes = NODE_CONFIG['new_nodes']

    # check if the new nodes already exists
    #for node_ip, node_disks in new_nodes.items():
    #    if node_ip in old_nodes:
    #        print "update already exists storage node: %s" % node_ip
    #        del old_nodes[node_ip]

    # generate puppet manifest files
    memcache_servers = []
    for fqdn in old_nodes.iterkeys():
        memcache_servers.append('%s:11221' % old_nodes[fqdn]['ip'])
    for fqdn in new_nodes.iterkeys():
        memcache_servers.append('%s:11221' % new_nodes[fqdn]['ip'])
    generate_manifest_file(new_nodes, memcache_servers)

    # trigger the new node to run puppet agent
    for fqdn in new_nodes.iterkeys():
        print "installing new node %s ..." % new_nodes[fqdn]['ip']
        if ssh_execute(new_nodes[fqdn]['ip'], ["puppet agent -vt"]):
            old_nodes[fqdn] = new_nodes[fqdn]

    # regenerate ring file
    master_node = DEFAULT_CONFIG.get('master_node')
    print "updating ring files on %s ..." % master_node
    ssh_execute(master_node, ["puppet agent -vt"])

    # generate puppet manifest files again
    memcache_servers = []
    for fqdn in old_nodes.iterkeys():
        memcache_servers.append('%s:11221' % old_nodes[fqdn]['ip'])
    generate_manifest_file(old_nodes, memcache_servers)
    # update all nodes's ring file
    for fqdn in old_nodes.iterkeys():
        print "updating ring files on %s ..." % old_nodes[fqdn]['ip']
        ssh_execute(old_nodes[fqdn]['ip'], ["puppet agent -vt"])

    # update config file
    write_config_file(config_file)


if __name__ == '__main__':
    main()
