node 'swift' {
  class  {'openstack::swift::ha':
      swift_user_password     => 'swift',
      proxy_pipeline          => ['catch_errors', 'healthcheck', 'cache','swift3','tempauth','proxy-server'],
      memcache_servers        => ['192.168.2.13:11211','192.168.2.41:11211'],
      swift_zone              => '1',
   }
}

node 'nginx' {
  class {'keepalived':
    priority1       => '100',
    priority2       => '101',
    state1          => 'BACKUP',
    state2          => 'MASTER',
    vip_address1    => '192.168.2.55',
    vip_address2    => '192.168.2.56',
 }
  class {'nginx':}
  nginx::resource::upstream { 'swift':
     ensure  => present,
     members => [
     '192.168.2.13:8080 weight=1 max_fails=0 fail_timeout=60s',
     '192.168.2.19:8080 weight=1 max_fails=0 fail_timeout=60s',
     '192.168.2.32:8080 weight=1 max_fails=0 fail_timeout=60s',
   ],
 }

 nginx::resource::vhost { 'swift.ustack.com':
   listen_ip    => '0.0.0.0',
   listen_port  => '8080',
   ensure       => present,
   proxy        => 'http://swift',
  }
}
