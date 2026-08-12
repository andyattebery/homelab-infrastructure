{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    nixpkgs-unstable.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    dsm = {
      url = "github:andyattebery/dashboard-services-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nim = {
      url = "github:andyattebery/network-inventory-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Currently imported by no host. pi-rack used its raspberry-pi-4 module until that was
    # replaced by nixos-raspberrypi (see nix/docs/raspberry-pi.md), and the x86 hosts are
    # Proxmox VMs with no hardware quirks to patch. Kept because it is the obvious source
    # for the next piece of bare metal; drop it if that never arrives.
    nixos-hardware = {
      url = "github:NixOS/nixos-hardware";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    deploy-rs = {
      url = "github:serokell/deploy-rs";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Deliberately NO inputs.nixpkgs.follows, unlike every other input above.
    # Its kernel and firmware come from its own locked nixpkgs via
    # nixos-raspberrypi.packages.<system>; making it follow ours produces different
    # derivations, rebuilds the vendor kernel from source, and misses
    # nixos-raspberrypi.cachix.org entirely. Do not "tidy" this.
    # See nix/docs/raspberry-pi.md.
    nixos-raspberrypi.url = "github:nvmd/nixos-raspberrypi/main";
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, sops-nix, dsm, nim, nixos-hardware, deploy-rs, nixos-raspberrypi, ... }:
  let
    inherit (nixpkgs) lib;
    vars = import ./secrets/vars.nix;

    # nixpkgs with the deploy-rs overlay applied, but forcing deploy-rs's binary
    # to come from nixpkgs (served from the binary cache) instead of being built
    # from source. Keeps the flake's `lib` for activation. Per deploy-rs README.
    deployPkgs = let
      mk = system: let pkgs = import nixpkgs { inherit system; };
      in import nixpkgs {
        inherit system;
        overlays = [
          deploy-rs.overlays.default
          (final: prev: {
            deploy-rs = { inherit (pkgs) deploy-rs; lib = prev.deploy-rs.lib; };
          })
        ];
      };
    in {
      x86_64-linux = mk "x86_64-linux";
      aarch64-linux = mk "aarch64-linux";
      aarch64-darwin = mk "aarch64-darwin";
    };

    # Everything every host gets. base.nix pulls in sops-nix and node_exporter itself;
    # capability modules (tailscale, nut, docker-host, dsm-provider), hardware modules
    # (rpi4, proxmox-guest) and stack bundles (network.nix) are opted into by the host
    # file. Adding a host means adding a directory under hosts/ -- nothing here changes.
    mkHost = hostname: lib.nixosSystem {
      specialArgs = {
        inherit sops-nix nixpkgs-unstable vars;
        # Consumed by host files that import input-derived modules:
        # nixos-raspberrypi's board modules read nixos-raspberrypi.packages.<system>
        # directly, and dsm/nim expose nixosModules the hosts import by hand. Unused
        # module args are lazy, so passing all of them to every host costs nothing.
        inherit nixos-raspberrypi dsm nim;
      };
      modules = [
        ./modules/base.nix
        ./hosts/${hostname}
      ];
    };

    # hosts/ has one directory per host. hosts/proxmox-vm-hardware.nix is a file, so
    # filtering readDir on "directory" drops it without naming it.
    hostDirs = lib.filterAttrs (_: type: type == "directory") (builtins.readDir ./hosts);

    # proxmox-template is the one host not built by mkHost: it is a bare bootstrap image
    # with root SSH and deliberately no base.nix, no sops and no services user, so it must
    # not receive the foundation. Excluding it here also keeps it out of deploy.nodes --
    # it is never a deploy target. install-proxmox-template.sh:55 installs it by this exact
    # attribute name, so do not rename it.
    managedHosts = builtins.removeAttrs hostDirs [ "proxmox-template" ];
  in {
    nixosConfigurations = (builtins.mapAttrs (hostname: _: mkHost hostname) managedHosts) // {
      proxmox-template = lib.nixosSystem {
        modules = [
          { nixpkgs.hostPlatform = "x86_64-linux"; }
          ./hosts/proxmox-template
        ];
      };
    };

    # One node per managed host, all identical in shape. The target architecture is read
    # back out of the host's own evaluated config rather than restated here; nothing under
    # nixosConfigurations reads deploy, so there is no cycle. mapAttrs is lazy per
    # attribute and deploy-rs narrows `nodes` to the one being deployed before serialising,
    # so `deploy .#some-host` never forces the others.
    deploy.nodes = builtins.mapAttrs (hostname: _: {
      hostname = "${hostname}.${vars.domainName}";
      sshUser = "services";
      remoteBuild = true;
      profiles.system = {
        user = "root";
        path = deployPkgs.${self.nixosConfigurations.${hostname}.config.nixpkgs.hostPlatform.system}
          .deploy-rs.lib.activate.nixos self.nixosConfigurations.${hostname};
      };
    }) managedHosts;

    packages.x86_64-linux.deploy-rs = deployPkgs.x86_64-linux.deploy-rs.deploy-rs;
    packages.aarch64-linux.deploy-rs = deployPkgs.aarch64-linux.deploy-rs.deploy-rs;
    packages.aarch64-darwin.deploy-rs = deployPkgs.aarch64-darwin.deploy-rs.deploy-rs;

    # checks = builtins.mapAttrs (system: deployLib: deployLib.deployChecks self.deploy) deploy-rs.lib;
  };
}
