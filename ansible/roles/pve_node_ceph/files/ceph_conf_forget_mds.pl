#!/usr/bin/perl
# Forget a metadata server in the cluster's ceph.conf: drop its [mds.<id>]
# section under PVE's cluster lock and through PVE's own parser and writer —
# the first thing `pveceph mds destroy` does (MDS.pm destroymds, pve-manager
# 9.2.11) — for the case where the daemon is already gone and `pveceph mds
# create` aborts on the leftover section.
#
#   ceph_conf_forget_mds.pl <mds id>
#
# Prints "changed" or "unchanged"; exits non-zero on any error. The pure part
# is forget_mds(), exercised by ../tests/test.yml with no PVE modules present.
use strict;
use warnings;

# Edits the parsed config in place. Returns 1 if anything changed.
sub forget_mds {
    my ($cfg, $mdsid) = @_;
    return (delete $cfg->{"mds.$mdsid"}) ? 1 : 0;
}

unless (caller) {
    die "usage: $0 <mds id>\n" if scalar(@ARGV) != 1;
    my ($mdsid) = @ARGV;

    require PVE::Cluster;
    require PVE::CephConfig; # registers the ceph.conf parser/writer with pmxcfs

    my $changed = 0;
    PVE::Cluster::cfs_lock_file(
        'ceph.conf',
        undef,
        sub {
            my $cfg = PVE::Cluster::cfs_read_file('ceph.conf');
            $changed = forget_mds($cfg, $mdsid);
            PVE::Cluster::cfs_write_file('ceph.conf', $cfg) if $changed;
        },
    );
    die $@ if $@;

    print $changed ? "changed\n" : "unchanged\n";
}

1;
