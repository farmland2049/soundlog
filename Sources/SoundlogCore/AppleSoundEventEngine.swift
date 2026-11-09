#if canImport(SoundAnalysis) && canImport(AVFoundation)
import Foundation
import SoundAnalysis
import AVFoundation

/// SoundAnalysis adapter. SDK category availability and API behavior still require Mac validation.
public struct AppleSoundEventEngine: SoundEventEngine {
    public let identifier = "apple-sound-analysis-version1"
    public init() {}

    public static func knownClassifications() throws -> [String] {
        try SNClassifySoundRequest(classifierIdentifier: .version1).knownClassifications
    }

    public func classify(file: URL) async throws -> SoundEventEngineResult {
        let analyzer = try SNAudioFileAnalyzer(url: file)
        let request = try SNClassifySoundRequest(classifierIdentifier: .version1)
        let observer = SoundClassificationObserver()
        try analyzer.add(request, withObserver: observer)
        await analyzer.analyze()
        if let error = observer.error { throw error }
        return SoundEventEngineResult(windows: observer.windows)
    }
}

private final class SoundClassificationObserver: NSObject, SNResultsObserving, @unchecked Sendable {
    private let lock = NSLock()
    private var collected: [SoundClassificationWindow] = []
    private var failure: Error?
    var windows: [SoundClassificationWindow] { lock.lock(); defer { lock.unlock() }; return collected }
    var error: Error? { lock.lock(); defer { lock.unlock() }; return failure }

    func request(_ request: SNRequest, didProduce result: SNResult) {
        guard let result = result as? SNClassificationResult else { return }
        let range = result.timeRange
        let start = range.start.seconds
        let end = range.start.seconds + range.duration.seconds
        let candidates = result.classifications.map { SoundEventCandidate(category: $0.identifier, confidence: Double($0.confidence)) }
        lock.lock(); collected.append(SoundClassificationWindow(start: start, end: end, candidates: candidates)); lock.unlock()
    }

    func request(_ request: SNRequest, didFailWithError error: Error) { lock.lock(); failure = error; lock.unlock() }
    func requestDidComplete(_ request: SNRequest) {}
}
#endif
