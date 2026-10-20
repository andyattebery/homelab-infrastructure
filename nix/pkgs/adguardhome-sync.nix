{ stdenv, fetchurl }:
let
  arch = if stdenv.hostPlatform.isAarch64 then "arm64" else "amd64";
in stdenv.mkDerivation rec {
  pname = "adguardhome-sync";
  version = "0.9.4";
  src = fetchurl {
    url = "https://github.com/bakito/adguardhome-sync/releases/download/v${version}/adguardhome-sync_${version}_linux_${arch}.tar.gz";
    hash = {
      amd64 = "sha256-tFHTEFTZEsKXO9pXk+xvU4q4NOM15x2VnxVhz3Wyyd4=";
      arm64 = "sha256-Xjdq4nSW4zT00GdyWzypvASDkt93Ae0Ikjjjy+ZTECQ=";
    }.${arch};
  };
  sourceRoot = ".";
  installPhase = ''
    install -Dm755 adguardhome-sync $out/bin/adguardhome-sync
  '';
}
