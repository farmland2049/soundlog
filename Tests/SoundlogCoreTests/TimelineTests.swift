import XCTest
@testable import SoundlogCore

final class TimelineTests: XCTestCase {
    func testParsesFilenameClockWithoutTimezone() throws {
        let start = try RecordingStart(filename: "20240229010102.mp3")
        XCTAssertEqual(try start.timestamp(atOffsetSeconds: 0), "2024-02-29T01:01:02.000")
    }

    func testMacVerifySyntheticInputFilenamePassesProjectParser() throws {
        XCTAssertNoThrow(try RecordingStart(filename: "20261110120000.wav"))
        XCTAssertThrowsError(try RecordingStart(filename: "20261110120000-synthetic.wav"))
    }

    func testRejectsMalformedFilenameAndInvalidDate() {
        XCTAssertThrowsError(try RecordingStart(filename: "20261107100316-copy.mp3"))
        XCTAssertThrowsError(try RecordingStart(filename: "20251301120000.mp3"))
        XCTAssertThrowsError(try RecordingStart(filename: "20250229000000.mp3"))
    }

    func testAddsOffsetAcrossMidnightWithoutCompressingTime() throws {
        let start = try RecordingStart(filename: "20240229235959.mp3")
        XCTAssertEqual(try start.timestamp(atOffsetSeconds: 2), "2024-03-01T00:00:01.000")
        XCTAssertEqual(try start.timestamp(atOffsetSeconds: 90), "2024-03-01T00:01:29.000")
    }

    func testFractionalOffsetIsRenderedToMilliseconds() throws {
        let start = try RecordingStart(filename: "20261107070318.mp3")
        XCTAssertEqual(try start.timestamp(atOffsetSeconds: 1.25), "2026-11-07T07:03:19.250")
    }

    func testRejectsNegativeAndNonFiniteOffsets() throws {
        let start = try RecordingStart(filename: "20261107070318.mp3")
        XCTAssertThrowsError(try start.timestamp(atOffsetSeconds: -0.1))
        XCTAssertThrowsError(try start.timestamp(atOffsetSeconds: .infinity))
        XCTAssertThrowsError(try start.timestamp(atOffsetSeconds: .nan))
    }

    func testValidatesRangesAndAudioBounds() throws {
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: -1, endOffsetSeconds: 2))
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: 2, endOffsetSeconds: 2))
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: .nan, endOffsetSeconds: 2))
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: .infinity))
        XCTAssertThrowsError(try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: 11, durationSeconds: 10))
        XCTAssertNoThrow(try AudioTimeRange(startOffsetSeconds: 0, endOffsetSeconds: 10, durationSeconds: 10))
    }

    func testChronologicalRangesMayOverlapButMayNotMoveBackwards() throws {
        let first = try AudioTimeRange(startOffsetSeconds: 1, endOffsetSeconds: 4)
        let overlapping = try AudioTimeRange(startOffsetSeconds: 3, endOffsetSeconds: 5)
        XCTAssertNoThrow(try AudioTimeRange.validateChronological([first, overlapping]))

        let earlier = try AudioTimeRange(startOffsetSeconds: 0.5, endOffsetSeconds: 2)
        XCTAssertThrowsError(try AudioTimeRange.validateChronological([first, earlier]))
    }
}
