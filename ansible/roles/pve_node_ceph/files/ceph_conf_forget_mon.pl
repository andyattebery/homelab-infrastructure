#!/usr/bin/perl
# Forget a monitor in the cluster's ceph.conf: drop its [mon.<id>] section and
# its address from mon_host, under PVE's cluster lock and through PVE's own
# parser and writer — what `pveceph mon destroy` does, except this also works
# when the monitor is already out of the monmap, which destroy cannot handle
# (it reads the address to drop from the monmap; MON.pm, pve-manager 9.2.11).
#
#   ceph_conf_forget_mon.pl <mon id> <mon ip>
#
# Prints "changed" or "unchanged"; exits non-zero on any error. The pure part
# is forget_mon(), exercised by ../tests/test.yml with no PVE modules present.
use strict;
use warnings;

# Edits the parsed config in place. Returns 1 if anything changed.
sub forget_mon {
    my ($cfg, $monid, $ip) = @_;
    my $changed = 0;

    $changed = 1 if delete $cfg->{"mon.$monid"};

    my $monhost = $cfg->{global}->{mon_host};
    if (defined($monhost) && length($monhost)) {
        # Vector form ([v2:ip:3300/0,v1:ip:6789/0]) is not handled here; PVE
        # writes plain addresses on this cluster. Refuse rather than mangle.
        die "mon_host uses the vector form; not touching it: $monhost\n" if $monhost =~ /\[/;

        my @tokens = split(/[\s,;]+/, $monhost);
        my @kept = grep { $_ ne $ip } @tokens;
        if (scalar(@kept) != scalar(@tokens)) {
            $cfg->{global}->{mon_host} = join(' ', @kept);
            $changed = 1;
        }
    }
    return $changed;
}

unless (caller) {
    die "usage: $0 <mon id> <mon ip>\n" if scalar(@ARGV) != 2;
    my ($monid, $ip) = @ARGV;

    require PVE::Cluster;
    require PVE::CephConfig; # registers the ceph.conf parser/writer with pmxcfs

    my $changed = 0;
    PVE::Cluster::cfs_lock_file(
        'ceph.conf',
        undef,
        sub {
            my $cfg = PVE::Cluster::cfs_read_file('ceph.conf');
            $changed = forget_mon($cfg, $monid, $ip);
            PVE::Cluster::cfs_write_file('ceph.conf', $cfg) if $changed;
        },
    );
    die $@ if $@;

    print $changed ? "changed\n" : "unchanged\n";
}

1;
