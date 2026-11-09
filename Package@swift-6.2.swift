// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "Soundlog",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "SoundlogCore", targets: ["SoundlogCore"]),
        .executable(name: "SoundlogCLI", targets: ["SoundlogCLI"])
    ],
    dependencies: [
        .package(url: "https://github.com/FluidInference/FluidAudio.git", exact: "0.17.7", traits: [])
    ],
    targets: [
        .target(
            name: "SoundlogCore",
            dependencies: [
                .product(name: "FluidAudio", package: "FluidAudio", condition: .when(platforms: [.macOS]))
            ],
            resources: [.process("ModelManifests")]
        ),
        .executableTarget(name: "SoundlogCLI", dependencies: ["SoundlogCore"]),
        .testTarget(name: "SoundlogCoreTests", dependencies: ["SoundlogCore"])
    ]
)
