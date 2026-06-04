{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    dsm = {
      url = "github:andyattebery/dashboard-services-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nixos-hardware = {
      url = "github:NixOS/nixos-hardware";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, sops-nix, dsm, nixos-hardware, ... }:
  let
    mkHost = hostname: system: extraModules: nixpkgs.lib.nixosSystem {
      specialArgs = {
        inherit sops-nix;
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
        ./modules/docker-host.nix
        ./modules/network.nix
        dsm.nixosModules.dsm-provider
      ];
      network-02 = mkHost "network-02" "aarch64-linux" [
        ./modules/tailscale.nix
        ./modules/docker-host.nix
        ./modules/network.nix
        ./modules/nut.nix
        nixos-hardware.nixosModules.raspberry-pi-4
        dsm.nixosModules.dsm-provider
      ];
      network-03 = mkHost "network-03" "x86_64-linux" [
        ./modules/tailscale.nix
        ./modules/docker-host.nix
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
  };
}
