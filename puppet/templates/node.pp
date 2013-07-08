node '%(node_fqdn)s' {
    class  {'openstack::swift::ha':
        memcache_servers        => %(memcache_servers)s,
        proxy_pipeline          => ['catch_errors', 'healthcheck', 'cache', 'swift3', 'tempauth', 'proxy-server'],
        remote_log_host         => '%(remote_log_host)s',
        swift_zone              => '%(swift_zone)s',
        swift_local_net_ip      => %(swift_local_net_ip)s,
        storage_devices         => %(storage_devices)s,
    }
}
