import Foundation
import Observation

// Mirrors SCHEMA.md (schema_version 1). Decoded with .convertFromSnakeCase.

struct Meta: Decodable, Sendable {
    let schemaVersion: Int
    let fromCycle: String
    let toCycle: String
    let upcoming: Bool
    let includesCharts: Bool
    let changedAirports: Int
    let generated: String

    /// how long ago amend.watch last rebuilt its data (it rebuilds at least daily); nil if unreadable
    var age: TimeInterval? {
        _ = CycleClock.shared.tick
        let f = ISO8601DateFormatter()
        return f.date(from: generated).map { ServerClock.now.timeIntervalSince($0) }
    }

    /// past this the app says the data may be out of date, same as the site (36 hours)
    var isStale: Bool { (age ?? 0) > 36 * 3600 }
}

struct Counts: Decodable, Sendable, Hashable {
    let action: Int
    let ifr: Int
    let fyi: Int
    var total: Int { action + ifr + fyi }
}

struct LatestIndex: Decodable, Sendable {
    let schemaVersion: Int
    let fromCycle: String
    let toCycle: String
    let airports: [String: Counts]
}

struct AirportChanges: Decodable, Sendable {
    let schemaVersion: Int
    let airport: String
    let fromCycle: String
    let toCycle: String
    let counts: Counts
    let changes: [Change]
}

struct AirportHistory: Decodable, Sendable {
    let schemaVersion: Int
    let airport: String
    let firstCycle: String
    let lastCycle: String
    let entries: [Change]
}

struct AirportDirectory: Decodable, Sendable {
    let schemaVersion: Int
    let cycle: String
    let airports: [AirportInfo]
}

struct AirportInfo: Decodable, Sendable, Identifiable, Hashable {
    let id: String
    let icao: String?
    let name: String
    let city: String?
    let state: String?
    let type: String?
    let lat: Double?
    let lon: Double?

    /// "Daytona Beach, FL"
    var location: String {
        [city, state].compactMap { $0 }.joined(separator: ", ")
    }
}

/// One change. History entries are the same shape plus `cycle` / `fromCycle`.
struct Change: Decodable, Identifiable, Hashable, Sendable {
    let id: String
    let priority: String
    let category: String
    let kind: String
    let summary: String
    let source: String
    let original: String?
    /// why a remark still reads in FAA words, ready to show ("Kept in the FAA's words: ...")
    let untranslated: String?
    let fields: [FieldChange]?
    let details: [String]?
    let procedures: Procedures?
    let chart: Chart?
    let cycle: String?        // history only
    let fromCycle: String?    // history only

    var level: Priority { Priority(rawValue: priority) ?? .fyi }
}

struct FieldChange: Decodable, Sendable, Hashable {
    let field: String
    let old: String
    let new: String
}

struct Procedures: Decodable, Sendable, Hashable {
    let updated: [String]
    let removed: [String]
}

struct Chart: Decodable, Sendable, Hashable {
    let code: String
    let name: String
    let amdt: String?
    let pdf: String?

    /// "Amdt 11C" / "Original" / nil
    var amdtLabel: String? {
        guard let amdt, !amdt.isEmpty else { return nil }
        return ["0", "ORIG"].contains(amdt.uppercased()) ? "Original" : "Amdt \(amdt)"
    }
}

enum Priority: String, CaseIterable, Identifiable, Sendable {
    case action, ifr, fyi
    var id: String { rawValue }

    var title: String {
        switch self {
        case .action: "Action"
        case .ifr: "IFR procedures"
        case .fyi: "FYI"
        }
    }
}

/// the clock the 0901Z changeover runs on: this device's, unless it's more than 2s off amend.watch's (the Date
/// header on every API response). a phone set 10 minutes fast mustn't show the new cycle as in effect at 0851Z
enum ServerClock {
    private static var offset: TimeInterval = 0
    static var now: Date { Date.now.addingTimeInterval(offset) }

    static func update(_ response: HTTPURLResponse, sent: Date) {
        guard let header = response.value(forHTTPHeaderField: "Date"),
              let server = httpDate.date(from: header) else { return }
        // the header is whole seconds; compare its middle with the middle of the round trip
        let mid = sent.addingTimeInterval(Date.now.timeIntervalSince(sent) / 2)
        let skew = server.addingTimeInterval(0.5).timeIntervalSince(mid)
        offset = abs(skew) > 2 ? skew : 0
    }

    private static let httpDate: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "GMT")
        f.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return f
    }()
}

/// redraws every view that asked Cycle.isInEffect / daysUntil: when the app comes back to the
/// foreground, when new meta loads, and at the 0901Z changeover itself while a screen is open
@Observable
final class CycleClock {
    static let shared = CycleClock()
    private(set) var tick = 0
    @ObservationIgnored private var wait: Task<Void, Never>?

    func recheck(_ cycle: String?) {
        tick += 1
        wait?.cancel()
        wait = nil
        guard let cycle, let t = Cycle.effectiveInstant(cycle) else { return }
        let seconds = t.timeIntervalSince(ServerClock.now)
        guard seconds > 0, seconds < 2 * 86400 else { return }
        wait = Task { [weak self] in
            try? await Task.sleep(for: .seconds(seconds + 0.05))
            if !Task.isCancelled { self?.recheck(cycle) }
        }
    }
}

/// FAA cycle dates ("2026-10-01"). Everything in UTC so a cycle never shows as the day before.
enum Cycle {
    private static let utc = TimeZone(identifier: "UTC")!

    private static let parser: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = utc
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    private static let efbFormatter: DateFormatter = {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = utc
        f.dateFormat = "dd MMM yyyy"
        return f
    }()

    static func date(_ cycle: String) -> Date? { parser.date(from: cycle) }

    static func string(_ date: Date) -> String { parser.string(from: date) }

    /// "01 Oct 2026"
    static func efb(_ cycle: String) -> String {
        guard let d = date(cycle) else { return cycle }
        return efbFormatter.string(from: d)
    }

    /// "03 Sep"
    static func efbShort(_ cycle: String) -> String {
        String(efb(cycle).prefix(6))
    }

    /// "2026-10-01" shifted by n days (a cycle is valid until the day before the next one)
    static func shift(_ cycle: String, days: Int) -> String {
        guard let d = date(cycle) else { return cycle }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = utc
        return cal.date(byAdding: .day, value: days, to: d).map { string($0) } ?? cycle
    }

    /// FAA cycles change over at 0901Z on the effective date (what the charts print:
    /// "0901Z 03 SEP 2026 to 0901Z 01 OCT 2026")
    static func effectiveInstant(_ cycle: String) -> Date? {
        date(cycle).map { $0.addingTimeInterval(9 * 3600 + 60) }
    }

    static func isInEffect(_ cycle: String) -> Bool {
        _ = CycleClock.shared.tick   // so SwiftUI redraws when it moves
        guard let t = effectiveInstant(cycle) else { return true }
        return ServerClock.now >= t
    }

    /// days from today until the cycle takes effect (negative = already effective)
    static func daysUntil(_ cycle: String) -> Int? {
        _ = CycleClock.shared.tick
        guard let d = date(cycle) else { return nil }
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = utc
        let today = cal.startOfDay(for: ServerClock.now)
        return cal.dateComponents([.day], from: today, to: d).day
    }
}
