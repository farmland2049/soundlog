// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Soundlog",
    products: [
        .library(name: "SoundlogCore", targets: ["SoundlogCore"])
    ],
    targets: [
        .target(name: "SoundlogCore"),
        .testTarget(name: "SoundlogCoreTests", dependencies: ["SoundlogCore"])
    ]
)
