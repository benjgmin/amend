import SwiftUI  // for Array.remove(atOffsets:) and move(fromOffsets:toOffset:)
import Observation

@MainActor
@Observable
final class AirportStore {
    private(set) var saved: [String] = []
    private(set) var home: String?
    private(set) var meta: Meta?
    private(set) var index: LatestIndex?
    private(set) var airports: [AirportInfo] = []
    private(set) var isLoading = false
    var errorMessage: String?

    private var byID: [String: AirportInfo] = [:]

    /// airports.json is ~2 MB, so keep a copy on disk: instant names at launch, works offline
    private let directoryCache = URL.cachesDirectory.appending(path: "airports.json")

    init() {
        let d = UserDefaults.standard
        saved = d.stringArray(forKey: SettingsKey.saved) ?? []
        home = d.string(forKey: SettingsKey.home)
        if let data = try? Data(contentsOf: directoryCache) {
            applyDirectory(data)
        }
    }

    // MARK: lookups

    func counts(for id: String) -> Counts? { index?.airports[id] }
    func info(for id: String) -> AirportInfo? { byID[id] }
    func isSaved(_ id: String) -> Bool { saved.contains(id) }

    /// saved airports except home, in the user's order
    var others: [String] { saved.filter { $0 != home } }

    /// ranked: exact id/ICAO, then id/ICAO prefix, then name, then city.
    /// within a rank, real airports with an ICAO id (towered/bigger fields) come first.
    func search(_ raw: String, limit: Int = 40) -> [AirportInfo] {
        let q = raw.trimmingCharacters(in: .whitespaces).uppercased()
        guard !q.isEmpty else { return [] }
        var scored: [(Int, AirportInfo)] = []
        for a in airports {
            let icao = a.icao ?? ""
            let name = a.name.uppercased()
            let rank: Int
            if a.id == q || icao == q { rank = 0 }
            else if a.id.hasPrefix(q) || icao.hasPrefix(q) { rank = 1 }
            else if q.count >= 3 && name.hasPrefix(q) { rank = 2 }
            else if q.count >= 3 && (name.contains(q) || (a.city ?? "").uppercased().contains(q)) { rank = 3 }
            else { continue }
            var score = rank * 10
            if a.type != nil && a.type != "airport" { score += 4 }   // heliports, seaplane bases last
            if icao.isEmpty { score += 2 }                           // private strips after public fields
            scored.append((score, a))
        }
        return scored
            .sorted { ($0.0, $0.1.id.count, $0.1.id) < ($1.0, $1.1.id.count, $1.1.id) }
            .prefix(limit)
            .map(\.1)
    }

    // MARK: loading

    func refresh() async {
        isLoading = true
        defer { isLoading = false }
        do {
            async let m = API.meta()
            async let i = API.latestIndex()
            let newMeta = try await m
            let newIndex = try await i
            meta = newMeta
            index = newIndex
            errorMessage = nil
            if let newMeta { NotificationManager.markSeen(newMeta.toCycle) }
        } catch {
            errorMessage = error.localizedDescription
        }
        await refreshDirectory()
    }

    private func refreshDirectory() async {
        guard let data = try? await API.data("airports.json") else { return }
        if applyDirectory(data) {
            try? data.write(to: directoryCache, options: .atomic)
        }
    }

    @discardableResult
    private func applyDirectory(_ data: Data) -> Bool {
        guard let dir = try? API.decoder.decode(AirportDirectory.self, from: data) else { return false }
        airports = dir.airports
        byID = Dictionary(dir.airports.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return true
    }

    func clearDirectoryCache() {
        try? FileManager.default.removeItem(at: directoryCache)
    }

    // MARK: saved airports

    /// "kdab " -> "DAB". Returns nil if it doesn't look like an airport id.
    static func normalize(_ raw: String) -> String? {
        var id = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if id.count == 4, id.hasPrefix("K"), id.dropFirst().allSatisfy(\.isLetter) {
            id.removeFirst()
        }
        guard (2...4).contains(id.count), id.allSatisfy({ $0.isLetter || $0.isNumber }) else { return nil }
        return id
    }

    @discardableResult
    func add(_ raw: String) -> String? {
        guard let id = Self.normalize(raw) else { return nil }
        if !saved.contains(id) {
            saved.append(id)
            if saved.count == 1 && home == nil { setHome(id) }   // first airport becomes home
            persist()
        }
        return id
    }

    func remove(_ id: String) {
        saved.removeAll { $0 == id }
        if home == id { setHome(nil) }
        persist()
    }

    /// offsets are into `others`
    func removeOthers(at offsets: IndexSet) {
        let ids = offsets.map { others[$0] }
        saved.removeAll { ids.contains($0) }
        persist()
    }

    /// offsets are into `others`
    func moveOthers(from source: IndexSet, to destination: Int) {
        var list = others
        list.move(fromOffsets: source, toOffset: destination)
        saved = (home.map { [$0] } ?? []) + list
        persist()
    }

    func setHome(_ id: String?) {
        home = id
        if let id, !saved.contains(id) { saved.insert(id, at: 0) }
        UserDefaults.standard.set(id, forKey: SettingsKey.home)
        persist()
    }

    private func persist() {
        UserDefaults.standard.set(saved, forKey: SettingsKey.saved)
    }
}
