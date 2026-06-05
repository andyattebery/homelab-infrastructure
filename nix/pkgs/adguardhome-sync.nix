{ stdenv, fetchurl }:
let
  arch = if stdenv.hostPlatform.isAarch64 then "arm64" else "amd64";
in stdenv.mkDerivation rec {
  pname = "adguardhome-sync";
  version = "0.9.0";
  src = fetchurl {
    url = "https://github.com/bakito/adguardhome-sync/releases/download/v${version}/adguardhome-sync_${version}_linux_${arch}.tar.gz";
    hash = {
      amd64 = "sha256-RbcL5V5PsyycKXRdMrx1RauzWUtVRmTJ29qlKZvgDac=";
      arm64 = "sha256-V1d2K4W7g5aMinROauffkzoHxFWejztnyRvV9hJo97I=";
    }.${arch};
  };
  sourceRoot = ".";
  installPhase = ''
    install -Dm755 adguardhome-sync $out/bin/adguardhome-sync
  '';
}
