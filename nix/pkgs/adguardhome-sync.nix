{ stdenv, fetchurl }:
let
  arch = if stdenv.hostPlatform.isAarch64 then "arm64" else "amd64";
in stdenv.mkDerivation rec {
  pname = "adguardhome-sync";
  version = "0.9.2";
  src = fetchurl {
    url = "https://github.com/bakito/adguardhome-sync/releases/download/v${version}/adguardhome-sync_${version}_linux_${arch}.tar.gz";
    hash = {
      amd64 = "sha256-3HZnnkV/nKoKnW3vUqAAuUV38Pffn8W1hZCfV/HmFKY=";
      arm64 = "sha256-auDNLG9zgqUm5W5yl+Ooca3HrO4TAimgEMclUlO2hsA=";
    }.${arch};
  };
  sourceRoot = ".";
  installPhase = ''
    install -Dm755 adguardhome-sync $out/bin/adguardhome-sync
  '';
}
