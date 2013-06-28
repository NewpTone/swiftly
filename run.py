#!/usr/bin/env python

import argparse
import ConfigParser
import netaddr
import os
import paramiko
import string
import sys


CONFIG = dict()
TOPDIR = os.getcwd()
PUPPET_DIR = os.path.join(TOPDIR, "puppet")
TEMPLATE_DIR = os.path.join(TOPDIR, "templates")
MANIFEST_DIR = os.path.join(TOPDIR, "manifests")


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
    cfg = ConfigParser.ConfigParser()
    cfg.read(config_file)
    old_nodes = {}
    for conf in cfg.items("main"):
        CONFIG[conf[0]] = conf[1]
    for node in cfg.items("nodes"):
        node_ip = node[0]
        node_disks = node[1].split(',')
        old_nodes[node_ip] = node_disks
    CONFIG['old_nodes'] = old_nodes


def write_config_file(config_file):
    cfg = ConfigParser.ConfigParser()
    cfg.add_section("main")
    for conf in CONFIG:
        if not conf in ['new_nodes', 'old_nodes', 'swift_node']:
            cfg.set("main", conf, CONFIG[conf])
    old_nodes = CONFIG['old_nodes']
    cfg.add_section("nodes")
    for node_ip, node_disks in old_nodes.items():
        cfg.set("nodes", node_ip, node_disks)
    cfg.write(open(config_file, "w"))


def parse_cli_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config-file',
                        required=True,
                        help=('A file contains swift cluster config infos'),
                       )
    parser.add_argument('-a', '--add-nodes',
                        action='append',
                        required=True,
                        help=('Hosts and storage device to be added into '
                              'the swift cluster, for example ip:sdb,sdc'),
                       )

    parser.add_argument('-z', '--zone',
                        required=True,
                        help=('Add storage node to which zone.'),
                       )
    args = parser.parse_args()
    parse_config_file(args.config_file)
    new_nodes = {}
    for new_node in args.add_nodes:
        new_node_ip = new_node.split(':')[0]
        temp_string = new_node.split(':')[1]
        new_node_disks = temp_string.split(',')
        if is_validate_ip_address(new_node_ip):
            new_nodes[new_node_ip] = new_node_disks
    CONFIG['new_nodes'] = new_nodes
    CONFIG['swift_zone'] = args.zone
    return args.config_file


def ssh_execute(host, cmds):
    kwargs = {}
    kwargs['port'] = CONFIG.get('ssh_port', 22)
    kwargs['username'] = CONFIG.get("ssh_username")
    kwargs['password'] = CONFIG.get("ssh_password")
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


def get_node_fqdn(host):
    kwargs = {}
    kwargs['port'] = CONFIG.get('ssh_port', 22)
    kwargs['username'] = CONFIG.get("ssh_username")
    kwargs['password'] = CONFIG.get("ssh_password")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.load_system_host_keys()
    ssh.connect(host, **kwargs)
    stdin, out, err = ssh.exec_command("hostname -f")
    return string.strip(out.read())


def generate_manifest_file(nodes, memcache_servers):
    # read puppet storage node template
    with open(os.path.join(TEMPLATE_DIR, "node.pp")) as ifile:
        node_template = ifile.read()

    with open(os.path.join(MANIFEST_DIR, "site.pp"), "w") as ofile:
        for node_ip, node_disks in nodes.items():
            node_conf = {}
            node_conf['swift_zone'] = CONFIG['swift_zone']
            node_conf['user_password'] = CONFIG['user_password']
            node_conf['node_fqdn'] = get_node_fqdn(node_ip)
            node_conf['storage_devices'] = node_disks
            node_conf['memcache_servers'] = memcache_servers
            ofile.write(node_template % node_conf)


def main():
    # check all necessary directory
    check_puppet_dirs()

    # parse cli arguments
    config_file = parse_cli_arguments()

    # check if the new nodes already exists
    master_node = CONFIG['master_node']
    old_nodes = CONFIG['old_nodes']
    new_nodes = CONFIG['new_nodes']

    #for node_ip, node_disks in new_nodes.items():
    #    if node_ip in old_nodes:
    #        print "update already exists storage node: %s" % node_ip
    #        del old_nodes[node_ip]

    # generate puppet manifest files
    memcache_servers = ['%s:11221' % ip for ip in old_nodes.keys()]
    memcache_servers.extend(['%s:11221' % ip for ip in new_nodes.keys()])
    generate_manifest_file(new_nodes, memcache_servers)

    # trigger the new node to run puppet agent
    for node_ip, node_disks in new_nodes.items():
        print "installing new node %s ..." % node_ip
        if ssh_execute(node_ip, ["puppet agent -vt"]):
            old_nodes[node_ip] = node_disks
            del new_nodes[node_ip]

    # regenerate ring file
    print "updating ring files on %s ..." % master_node
    ssh_execute(master_node, ["puppet agent -vt"])

    # generate puppet manifest files again
    memcache_servers = ['%s:11221' % ip for ip in old_nodes.keys()]
    generate_manifest_file(old_nodes, memcache_servers)
    # update all nodes's ring file
    for node_ip, node_disks in old_nodes.items():
        print "updating ring files on %s ..." % node_ip
        ssh_execute(node_ip, ["puppet agent -vt"])

    # update config file
    write_config_file(config_file)


if __name__ == '__main__':
    main()
