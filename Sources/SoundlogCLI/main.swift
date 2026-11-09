import Foundation
import SoundlogCore

@main struct SoundlogCLI {
    static func main() async {
        do {
            let options = try CLIOptions.parse(Array(CommandLine.arguments.dropFirst()))
            let files = try InputEnumerator.files(at: options.input)
            let run = options.runDirectory ?? options.outputRoot.appendingPathComponent("run-\(ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-") )-\(UUID().uuidString.prefix(8))", isDirectory: true)
            try FileManager.default.createDirectory(at: run, withIntermediateDirectories: true)
            let manifest = try InputEnumerator.manifest(at: options.input)
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try AtomicFile.write(try encoder.encode(manifest), to: run.appendingPathComponent("manifest.json"))
            if options.command == .manifest { print("清单已写入: \(run.path)"); return }
            #if canImport(Speech) && canImport(AVFoundation)
            let engine = AppleSpeechEngine(localeIdentifier: options.parameters["locale"] ?? "zh-CN")
            let outcomes = await TranscriptionRun(engine: engine).process(files: files, runDirectory: run, parameters: options.parameters)
            for outcome in outcomes { if case .rerun(let reason) = outcome.decision, reason != "无记录" { fputs("转写处理 \(outcome.file.lastPathComponent): \(reason)\n", stderr) } }
            #else
            _ = files
            FileHandle.standardError.write(Data("错误: 本平台不支持苹果转写（Speech/AVFoundation 不可用）。清单已写入: \(run.path)\n".utf8))
            exit(2)
            #endif
        } catch {
            FileHandle.standardError.write(Data("错误: \(error)\n".utf8)); exit(2)
        }
    }
}

