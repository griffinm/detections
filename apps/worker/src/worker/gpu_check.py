"""GPU sanity check — run inside worker-gpu container."""

import sys


def main() -> None:
    print("Checking PyTorch CUDA availability...")
    try:
        import torch  # type: ignore[import-untyped]

        available = torch.cuda.is_available()
        print(f"  torch.cuda.is_available() = {available}")
        if available:
            print(f"  Device: {torch.cuda.get_device_name(0)}")
        else:
            print("  WARNING: CUDA not available", file=sys.stderr)
    except ImportError:
        print("  torch not installed (expected on CPU worker)", file=sys.stderr)


if __name__ == "__main__":
    main()
