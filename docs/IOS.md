# Build and install the iPhone app

The client is a UIKit / WKWebView app using the server's UI, with native camera
permissions, server settings and file sharing. It requires iOS 16 or newer.
It does not contain OCR weights or a preconfigured private server.

## GitHub Actions

The `Build iPhone IPA` workflow uses a macOS runner and XcodeGen to build for a
real iPhone, then packages an **unsigned IPA**. The `TailScan-IPA` artifact contains
the IPA and its SHA-256 hash. No Apple ID, signing certificate or provisioning
profile is stored in the workflow.

Download a release IPA or workflow artifact, then sign/install it using your
sideloading tool. On first launch, enter your own private TailScan URL. Enable
Tailscale on the iPhone and keep the backend available. Tapping a saved PDF opens
the native share sheet so you can choose Save to Files.

The public bundle ID is `org.tailscan.scanner`. Set your own identifier in
`ios/project.yml` if needed. Your local WKWebView draft data is separate from Safari;
permanent library documents are stored on the server.

## Local build on a Mac

```bash
brew install xcodegen
cd ios
xcodegen generate
open TailScan.xcodeproj
```

Choose your own signing configuration in Xcode for installation through Xcode.
The automated build deliberately disables code signing for later sideloading.

## Device checks

After signing, check camera/photo permissions, multi-page import, corner dragging,
filter switching, PDF sharing and reconnecting after Tailscale is toggled. A cloud
compile verifies the build; it cannot confirm permissions on your particular phone.
