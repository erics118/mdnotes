{
  description = "mdnotes dev shell";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-parts.url = "github:hercules-ci/flake-parts";
  };

  outputs =
    inputs@{ flake-parts, ... }:
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      perSystem =
        { pkgs, lib, ... }:
        {
          devShells.default = pkgs.mkShell {
            packages = with pkgs; [
              python313
              poppler-utils
              pyright
              ruff
              nodejs_22
            ];

            # pip wheels (numpy, grpcio, ...) are manylinux binaries that dlopen
            # libstdc++/zlib; on NixOS those aren't on the default loader path.
            shellHook = ''
              if [ ! -d venv ]; then
                python -m venv venv
                venv/bin/pip install -e ".[dev]" --quiet
              fi
            '' + lib.optionalString pkgs.stdenv.isLinux ''
              export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ]}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            '';
          };
        };
    };
}
