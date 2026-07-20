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
    nixos-hardware = {
      url = "github:NixOS/nixos-hardware";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    deploy-rs = {
      url = "github:serokell/deploy-rs";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, sops-nix, dsm, nim, nixos-hardware, deploy-rs, ... }:
  let
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
    mkHost = hostname: system: extraModules: nixpkgs.lib.nixosSystem {
      specialArgs = {
        inherit sops-nix nixpkgs-unstable;
        vars = import ./secrets/vars.nix;
      };
      modules = [
        { nixpkgs.hostPlatform = system; }
        sops-nix.nixosModules.sops
        ./modules/base.nix
        ./modules/monitoring.nix
        ./hosts/${hostname}
      ] ++ extraModules;
    };
  in {
    nixosConfigurations = {
      network-01 = mkHost "network-01" "x86_64-linux" [
        ./modules/tailscale.nix
        ./modules/network.nix
        dsm.nixosModules.dsm-provider
        nim.nixosModules.default
        ({ lib, pkgs, ... }: {
          nixpkgs.overlays = [ nim.overlays.default ];
          nixpkgs.config.allowUnfreePredicate = pkg:
            builtins.elem (lib.getName pkg) [ "1password-cli" ];
          services.network-inventory-manager.package = pkgs.network-inventory-manager;
        })
      ];
      pi-rack = mkHost "pi-rack" "aarch64-linux" [
        ./modules/tailscale.nix
        ./modules/network.nix
        ./modules/nut.nix
        nixos-hardware.nixosModules.raspberry-pi-4
        dsm.nixosModules.dsm-provider
      ];
      network-03 = mkHost "network-03" "x86_64-linux" [
        ./modules/tailscale.nix
        ./modules/network.nix
        dsm.nixosModules.dsm-provider
      ];
      proxmox-template = nixpkgs.lib.nixosSystem {
        modules = [
          { nixpkgs.hostPlatform = "x86_64-linux"; }
          ./hosts/proxmox-template
        ];
      };
      # END_HOSTS
    };

    deploy.nodes = let
      vars = import ./secrets/vars.nix;
      fqdn = name: "${name}.${vars.domainName}";
    in {
      network-01 = {
        hostname = fqdn "network-01";
        sshUser = "services";
        remoteBuild = true;
        profiles.system = {
          user = "root";
          path = deployPkgs.x86_64-linux.deploy-rs.lib.activate.nixos self.nixosConfigurations.network-01;
        };
      };
      network-03 = {
        hostname = fqdn "network-03";
        sshUser = "services";
        remoteBuild = true;
        profiles.system = {
          user = "root";
          path = deployPkgs.x86_64-linux.deploy-rs.lib.activate.nixos self.nixosConfigurations.network-03;
        };
      };
      pi-rack = {
        hostname = fqdn "pi-rack";
        sshUser = "services";
        remoteBuild = true;
        profiles.system = {
          user = "root";
          path = deployPkgs.aarch64-linux.deploy-rs.lib.activate.nixos self.nixosConfigurations.pi-rack;
        };
      };
    };

    packages.x86_64-linux.deploy-rs = deployPkgs.x86_64-linux.deploy-rs.deploy-rs;
    packages.aarch64-linux.deploy-rs = deployPkgs.aarch64-linux.deploy-rs.deploy-rs;
    packages.aarch64-darwin.deploy-rs = deployPkgs.aarch64-darwin.deploy-rs.deploy-rs;

    # checks = builtins.mapAttrs (system: deployLib: deployLib.deployChecks self.deploy) deploy-rs.lib;
  };
}
