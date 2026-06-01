{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    dsm = {
      url = "github:andyattebery/dashboard-services-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, sops-nix, dsm, ... }:
  let
    mkHost = hostname: extraModules: nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      specialArgs = {
        inherit sops-nix;
        vars = import ./secrets/vars.nix;
      };
      modules = [
        sops-nix.nixosModules.sops
        ./modules/base.nix
        ./modules/monitoring.nix
        ./hosts/${hostname}
      ] ++ extraModules;
    };
  in {
    nixosConfigurations = {
      network-01 = mkHost "network-01" [
        ./modules/tailscale.nix
        ./modules/docker-host.nix
        ./modules/network.nix
        dsm.nixosModules.dsm-provider
      ];
      network-03 = mkHost "network-03" [
        ./modules/tailscale.nix
        ./modules/docker-host.nix
        ./modules/network.nix
        dsm.nixosModules.dsm-provider
      ];
      proxmox-template = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [ ./hosts/proxmox-template ];
      };
      # END_HOSTS
    };
  };
}
