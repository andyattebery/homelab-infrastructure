{ stdenv, fetchurl }:
let
  arch = if stdenv.hostPlatform.isAarch64 then "arm64" else "amd64";
in stdenv.mkDerivation rec {
  pname = "adguardhome-sync";
  version = "0.9.3";
  src = fetchurl {
    url = "https://github.com/bakito/adguardhome-sync/releases/download/v${version}/adguardhome-sync_${version}_linux_${arch}.tar.gz";
    hash = {
      amd64 = "sha256-6sFctpHCHBiNhDVyRBX0r4wwU10GWBRbLHMKbN2Z0iw=";
      arm64 = "sha256-yxkJrZ9FFs8W46BuGV9AlMKaqXoalBio7frjUthpCYw=";
    }.${arch};
  };
  sourceRoot = ".";
  installPhase = ''
    install -Dm755 adguardhome-sync $out/bin/adguardhome-sync
  '';
}
