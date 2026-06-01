{ stdenv, fetchurl }:
let
  arch = if stdenv.hostPlatform.isAarch64 then "arm64" else "amd64";
in stdenv.mkDerivation rec {
  pname = "keepalived-exporter";
  version = "1.7.1";
  src = fetchurl {
    url = "https://github.com/mehdy/keepalived-exporter/releases/download/v${version}/keepalived-exporter_${version}_linux_${arch}.tar.gz";
    hash = {
      amd64 = "sha256-Ktsd1ipQzZj3I+qygkRCCGje4driqdLc0KXx7WR6X1k=";
      arm64 = "sha256-aHoTt7YEQbEEQcQ06KvJ3fEKUBpl9kDpxIIm7hZn7vk=";
    }.${arch};
  };
  sourceRoot = ".";
  installPhase = ''
    install -Dm755 keepalived-exporter $out/bin/keepalived-exporter
  '';
}
