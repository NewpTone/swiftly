node '%(fqdn)' {
  class  {'openstack::swift::ha':
      swift_user_password     => 'swift',
      proxy_pipeline          => ['catch_errors', 'healthcheck', 'cache','swift3','tempauth','proxy-server'],
      memcache_servers        => ['127.0.0.1:11211'],
      swift_zone              => '1',
   }
}
