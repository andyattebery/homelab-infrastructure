
## Restores

on backup-01, before a big restore to nas-01:
`sudo ip route add 192.168.1.232/32 dev enp3s0 src 192.168.1.249`
... run the restore (now 10G both directions) ...
`sudo ip route del 192.168.1.232/32 dev enp3s0`