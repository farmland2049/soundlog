// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Soundlog",
    products: [
        .library(name: "SoundlogCore", targets: ["SoundlogCore"]),
        .executable(name: "SoundlogCLI", targets: ["SoundlogCLI"])
    ],
    targets: [
        .target(name: "SoundlogCore"),
        .executableTarget(name: "SoundlogCLI", dependencies: ["SoundlogCore"]),
        .testTarget(name: "SoundlogCoreTests", dependencies: ["SoundlogCore"])
    ]
)
