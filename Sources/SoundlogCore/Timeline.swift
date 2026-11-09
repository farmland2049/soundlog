import Foundation

/// A timezone-free Gregorian clock parsed from the recording filename.
/// UTC is used only as an arithmetic coordinate for calendar rollover; it is
/// never emitted as a timezone or treated as the recording's actual timezone.
public struct RecordingStart: Equatable, Sendable {
    public let year: Int
    public let month: Int
    public let day: Int
    public let hour: Int
    public let minute: Int
    public let second: Int

    public init(filename: String) throws {
        let basename = URL(fileURLWithPath: filename).deletingPathExtension().lastPathComponent
        let bytes = Array(basename.utf8)
        guard bytes.count == 14, bytes.allSatisfy({ 48...57 ~= $0 }) else {
            throw TimelineError.invalidFilename
        }

        let parts = stride(from: 0, to: bytes.count, by: 2).map { start in
            Int(String(decoding: bytes[start..<(start + 2)], as: UTF8.self))!
        }
        let year = parts[0] * 100 + parts[1]
        let month = parts[2]
        let day = parts[3]
        let hour = parts[4]
        let minute = parts[5]
        let second = parts[6]

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var components = DateComponents()
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        components.year = year
        components.month = month
        components.day = day
        components.hour = hour
        components.minute = minute
        components.second = second

        guard let date = calendar.date(from: components),
              calendar.component(.year, from: date) == year,
              calendar.component(.month, from: date) == month,
              calendar.component(.day, from: date) == day,
              calendar.component(.hour, from: date) == hour,
              calendar.component(.minute, from: date) == minute,
              calendar.component(.second, from: date) == second else {
            throw TimelineError.invalidCalendarDate
        }

        self.year = year
        self.month = month
        self.day = day
        self.hour = hour
        self.minute = minute
        self.second = second
    }

    /// Returns the filename wall-clock time plus an original-audio offset.
    /// The output deliberately contains no timezone suffix.
    public func timestamp(atOffsetSeconds offset: Double) throws -> String {
        guard offset.isFinite, offset >= 0 else {
            throw TimelineError.invalidOffset
        }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var components = DateComponents()
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        components.year = year
        components.month = month
        components.day = day
        components.hour = hour
        components.minute = minute
        components.second = second

        guard let start = calendar.date(from: components) else {
            throw TimelineError.invalidCalendarDate
        }
        let result = start.addingTimeInterval(offset)
        guard result.timeIntervalSinceReferenceDate.isFinite else {
            throw TimelineError.invalidOffset
        }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSS"
        return formatter.string(from: result)
    }
}

/// An interval measured in seconds from the original audio's beginning.
public struct AudioTimeRange: Equatable, Sendable {
    public let startOffsetSeconds: Double
    public let endOffsetSeconds: Double

    public init(startOffsetSeconds: Double, endOffsetSeconds: Double, durationSeconds: Double? = nil) throws {
        guard startOffsetSeconds.isFinite, endOffsetSeconds.isFinite,
              startOffsetSeconds >= 0, endOffsetSeconds > startOffsetSeconds else {
            throw TimelineError.invalidRange
        }
        if let durationSeconds {
            guard durationSeconds.isFinite, durationSeconds >= 0,
                  endOffsetSeconds <= durationSeconds else {
                throw TimelineError.rangeOutsideAudio
            }
        }
        self.startOffsetSeconds = startOffsetSeconds
        self.endOffsetSeconds = endOffsetSeconds
    }

    /// Intervals may overlap; their starts must remain in chronological order.
    public static func validateChronological(_ ranges: [AudioTimeRange]) throws {
        for pair in zip(ranges, ranges.dropFirst()) where pair.1.startOffsetSeconds < pair.0.startOffsetSeconds {
            throw TimelineError.outOfOrderRanges
        }
    }
}

public enum TimelineError: Error, Equatable, Sendable {
    case invalidFilename
    case invalidCalendarDate
    case invalidOffset
    case invalidRange
    case rangeOutsideAudio
    case outOfOrderRanges
}
