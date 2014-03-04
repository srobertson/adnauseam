AdNauseam [![Build Status](https://travis-ci.org/trivio/adnauseam.png)](https://travis-ci.org/srobertson/adnauseam)
=========

Dynamic configuration templating system and process manager for processes that
you want to configure with data from etcd.

Inspired by confd but  eliminates the need to keep a configuration
file. All information is configured inside a template or via the command
line.

Quick Start
===========

Create a template with values to be relpaced by adnauseam enclused
in curly braces `{}`

For example here's a template to generate the hadoop configuration file core-site.xml.
Put the snipet below in a file named `core-site.xml.template`.

```XML
<configuration>
 <property>
  <name>fs.default.name</name>
  <value>hdfs://{namenode/address}:{namenode/port}</value>
 </property>
</configuration>
```

Now use adnauseam to launch a process that needs this configuration.

```Bash
$ adnauseam -t core-site.xml.template:/usr/lib/hadoop/conf/core-site.xml hadoop namednode
Monitoring namenode/address namenode/port for /usr/lib/hadoop/core-site.xml

```

The `-t <template path>:<output path>` instructs AdNauseam to generate the output file
based on the template. You can specify multipe `-t` pairs if you wish.

It this example AdNauseam reads the template core-site.xml.template and monitors
the keys found in the template `namednode/address` and `nammednode/port`. When both
of these values are present AdNauseam will generate `/usr/lib/hadoop/conf/core-site.xml`
and execute the command `hadoop namenode`

Let's mimic this in another terminal using `etcdctl` to set the values of 

`namenode/address` and `namenode/port`

```Bash
$ etcdctl set namenode/address 127.0.0.1
$ etcdctl set namenode/port 8020
```

In terminal running adnaseam you should see

```
[INFO] namenode/address updated to 127.0.0.1
[INFO] namenode/port uptade to 8020
[INFO] generating /usr/lib/hadoop/conf/core-site.xml
[INFO] (Re)launchnig hadoop namenode
```

AdNauseam will continue to monitor etcd for changes to the specified keys
and take the appropriat action based on changes.


For example if you update a key adnauseam will regenerate the config files
and reload your process

In  a seperate terminal:

```Bash
$ etcdctl set namenode/address 172.12.8.150
```

You'll see adnauseam update `core-site.xml' and relaunch the process:

```
[INFO] namenode/address update to 172.12.8.150
[INFO] generating /usr/lib/hadoop/conf/core-site.xml
[INFO] (Re)launching hadoop namenode
```

Removing keys needed by the template will remove the config files
and halt the process:

```Bash
$ etcdctl rm namenode/address
```

```
[INFO] namenode/address removed
[INFO] deleting /usr/lib/hadoop/conf/core-site.xml
[INFO] halting hadoop namenode
```

If later on these keys are set again. AdNauseam will relaunch the process.

