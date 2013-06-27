class {'puppet':}
class {'puppetdb':}
class {'puppetdb::master::config':}

Class['puppet']  -> Class['puppetdb::master::config'] -> Class['puppetdb']
