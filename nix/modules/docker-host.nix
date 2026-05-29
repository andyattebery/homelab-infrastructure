{ config, lib, pkgs, ... }:
let
  cfg = config.services.docker-compose;
  docker = config.virtualisation.docker.package;
  stackOpts = { name, ... }: {
    options = {
      composeFile = lib.mkOption { type = lib.types.path; };
      workingDirectory = lib.mkOption {
        type = lib.types.str;
        default = "/var/lib/docker-compose/${name}";
      };
      dataDirectory = lib.mkOption {
        type = lib.types.nullOr lib.types.str;
        default = null;
      };
      environment = lib.mkOption {
        type = lib.types.attrsOf lib.types.str;
        default = {};
      };
      environmentFiles = lib.mkOption {
        type = lib.types.listOf lib.types.path;
        default = [];
      };
      configFiles = lib.mkOption {
        type = lib.types.attrsOf (lib.types.submodule {
          options = {
            source = lib.mkOption { type = lib.types.path; };
            mode = lib.mkOption { type = lib.types.str; default = "0644"; };
          };
        });
        default = {};
      };
      configDirs = lib.mkOption {
        type = lib.types.attrsOf lib.types.path;
        default = {};
      };
    };
  };
in {
  options.services.docker-compose = lib.mkOption {
    type = lib.types.attrsOf (lib.types.submodule stackOpts);
    default = {};
  };

  options.services.docker-compose-defaults = {
    user = lib.mkOption {
      type = lib.types.str;
      default = "services";
    };
    dataDirectory = lib.mkOption {
      type = lib.types.str;
      default = "/data/docker";
    };
    domainName = lib.mkOption {
      type = lib.types.str;
      default = "";
    };
  };

  config = let
    defaults = config.services.docker-compose-defaults;
    userCfg = config.users.users.${defaults.user};
    defaultEnv = {
      PUID = toString userCfg.uid;
      PGID = toString config.users.groups.${userCfg.group}.gid;
      DOCKER_GID = toString config.users.groups.docker.gid;
      TZ = config.time.timeZone;
      DOMAIN_NAME = defaults.domainName;
      DOCKER_DATA_DIRECTORY = defaults.dataDirectory;
      HOSTNAME = config.networking.hostName;
    };
  in lib.mkIf (cfg != {}) {
    virtualisation.docker.enable = true;
    users.groups.docker.gid = lib.mkDefault 998;
    users.users.services.extraGroups = [ "docker" ];

    systemd.services = lib.mapAttrs' (name: stack:
      let
        dataDir = if stack.dataDirectory != null
          then stack.dataDirectory
          else "${defaults.dataDirectory}/${name}";
        uid = toString userCfg.uid;
        gid = toString config.users.groups.${userCfg.group}.gid;
        configSetup = lib.concatStringsSep "\n" (
          (lib.mapAttrsToList (dest: fileCfg: ''
            ${pkgs.coreutils}/bin/mkdir -p "$(dirname "${dataDir}/${dest}")"
            ${pkgs.coreutils}/bin/cp ${fileCfg.source} "${dataDir}/${dest}"
            chown ${uid}:${gid} "${dataDir}/${dest}"
            chmod ${fileCfg.mode} "${dataDir}/${dest}"
          '') stack.configFiles)
          ++ (lib.mapAttrsToList (dest: src: ''
            ${pkgs.coreutils}/bin/mkdir -p "${dataDir}/${dest}"
            ${pkgs.coreutils}/bin/cp -r ${src}/. "${dataDir}/${dest}"
            chown -R ${uid}:${gid} "${dataDir}/${dest}"
          '') stack.configDirs)
        );
      in lib.nameValuePair "docker-compose-${name}" {
        description = "Docker Compose: ${name}";
        after = [ "docker.service" "network-online.target" ];
        requires = [ "docker.service" ];
        wants = [ "network-online.target" ];
        wantedBy = [ "multi-user.target" ];
        path = [ docker ];
        environment = defaultEnv // stack.environment;

        serviceConfig = {
          Type = "simple";
          Restart = "always";
          WorkingDirectory = stack.workingDirectory;
          EnvironmentFile = stack.environmentFiles;
          ExecStartPre = [
            "+${pkgs.writeShellScript "docker-compose-${name}-setup" ''
              ${pkgs.coreutils}/bin/mkdir -p ${stack.workingDirectory}
              ${pkgs.coreutils}/bin/cp ${stack.composeFile} ${stack.workingDirectory}/docker-compose.yaml
              ${lib.optionalString (configSetup != "") ''
                ${pkgs.coreutils}/bin/mkdir -p ${dataDir}
                ${configSetup}
              ''}
            ''}"
          ];
          ExecStart = "${docker}/bin/docker compose up --remove-orphans";
          ExecStop = "${docker}/bin/docker compose down";
        };

        restartTriggers = [ stack.composeFile ]
          ++ (map (f: f.source) (lib.attrValues stack.configFiles))
          ++ (lib.attrValues stack.configDirs);
      }
    ) cfg;

    environment.systemPackages = [
      (pkgs.writeShellScriptBin "dcup" ''
        set -euo pipefail
        ${lib.concatStringsSep "\n" (lib.mapAttrsToList (k: v: "export ${k}=${v}") defaultEnv)}
        ${lib.concatMapStringsSep "\n" (name: let s = cfg.${name}; in ''
          echo "==> Pulling ${name}"
          for svc in $(${docker}/bin/docker compose -f "${s.workingDirectory}/docker-compose.yaml" config --services); do
            ${docker}/bin/docker compose -f "${s.workingDirectory}/docker-compose.yaml" pull "$svc"
          done
        '') (lib.attrNames cfg)}
        ${lib.concatMapStringsSep "\n" (name: ''
          echo "==> Restarting docker-compose-${name}"
          systemctl restart "docker-compose-${name}"
        '') (lib.attrNames cfg)}
        ${docker}/bin/docker system prune -f
      '')
    ];
  };
}
