import SwiftUI  // for Array.remove(atOffsets:) and move(fromOffsets:toOffset:)
import Observation

@MainActor
@Observable
final class AirportStore {
    /// your lists of airports, like the site's (no account: they live on this phone)
    private(set) var lists: [AirportList] = []
    /// the list the home screen shows, and where + adds
    private(set) var activeListID: String?
    /// pinned at the top of home; it doesn't have to be on a list
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
        home = d.string(forKey: SettingsKey.home)
        if let data = d.data(forKey: SettingsKey.lists),
           let stored = try? JSONDecoder().decode([AirportList].self, from: data) {
            lists = stored
        } else {
            // before lists there was one list of saved airports (home among them): it becomes "My airports"
            let old = (d.stringArray(forKey: SettingsKey.saved) ?? []).filter { $0 != home }
            if !old.isEmpty { lists = [AirportList(id: Self.newID(), name: "My airports", ids: old)] }
            persist()
        }
        activeListID = d.string(forKey: SettingsKey.activeList)
        if let data = try? Data(contentsOf: directoryCache) {
            applyDirectory(data)
        }
    }

    // MARK: lookups

    func counts(for id: String) -> Counts? { index?.airports[id] }
    func info(for id: String) -> AirportInfo? { byID[id] }

    /// every airport you keep: home first, then each list's, without repeats
    var saved: [String] {
        var seen = Set<String>()
        return ([home].compactMap { $0 } + lists.flatMap(\.ids)).filter { seen.insert($0).inserted }
    }

    /// on any list, or your home field
    func isSaved(_ id: String) -> Bool { home == id || lists.contains { $0.ids.contains(id) } }

    /// the list in use: the one you picked last, else the first
    var activeList: AirportList? { lists.first { $0.id == activeListID } ?? lists.first }

    func listsContaining(_ id: String) -> [AirportList] { lists.filter { $0.ids.contains(id) } }

    /// this cycle's changes at the airports you keep, for "coming up at your airports" on home
    private(set) var latest: [String: AirportChanges] = [:]

    /// the airports you keep that change this cycle, most action items first; the site caps it at 60 too
    var busyKept: [String] {
        saved.filter { counts(for: $0) != nil }
            .sorted { a, b in
                let x = counts(for: a)?.action ?? 0, y = counts(for: b)?.action ?? 0
                return x != y ? x > y : a < b
            }
    }

    /// fetches the changes behind busyKept that aren't loaded yet (URLSession caches the rest)
    func loadKept() async {
        let want = busyKept.prefix(60).filter { latest[$0]?.toCycle != index?.toCycle }
        guard !want.isEmpty else { return }
        let got = await withTaskGroup(of: (String, AirportChanges?).self) { group in
            for id in want { group.addTask { (id, try? await API.latest(id)) } }
            var out: [(String, AirportChanges)] = []
            for await (id, data) in group { if let data { out.append((id, data)) } }
            return out
        }
        for (id, data) in got { latest[id] = data }
    }

    /// the airports with the most action items this cycle, as on the site's home page (most changes breaks ties)
    private(set) var busiest: [String] = []

    private static func rank(_ index: LatestIndex?) -> [String] {
        guard let index else { return [] }
        return index.airports
            .sorted { a, b in
                (-a.value.action, -a.value.total, a.key) < (-b.value.action, -b.value.total, b.key)
            }
            .prefix(12)
            .map(\.key)
    }


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
            busiest = Self.rank(newIndex)
            CycleClock.shared.recheck(newMeta?.toCycle)
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

    // MARK: lists

    /// "kdab " -> "DAB". Returns nil if it doesn't look like an airport id.
    static func normalize(_ raw: String) -> String? {
        var id = raw.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        if id.count == 4, id.hasPrefix("K"), id.dropFirst().allSatisfy(\.isLetter) {
            id.removeFirst()
        }
        guard (2...4).contains(id.count), id.allSatisfy({ $0.isLetter || $0.isNumber }) else { return nil }
        return id
    }

    /// puts an airport on the list in use (starting "My airports" if there's no list yet). Never sets home.
    @discardableResult
    func add(_ raw: String) -> String? {
        guard let id = Self.normalize(raw) else { return nil }
        let list = activeList ?? createList("My airports")
        setOnList(id, list.id, true)
        return id
    }

    /// on or off one list
    func setOnList(_ id: String, _ listID: String, _ on: Bool) {
        guard let i = lists.firstIndex(where: { $0.id == listID }) else { return }
        if on {
            guard !lists[i].ids.contains(id), lists[i].ids.count < AirportList.maxAirports else { return }
            lists[i].ids.append(id)
        } else {
            lists[i].ids.removeAll { $0 == id }
        }
        persist()
    }

    /// same names as the site: trimmed, 60 characters at most, and a repeat gets " 2"
    @discardableResult
    func createList(_ name: String, ids: [String] = []) -> AirportList {
        let list = AirportList(id: Self.newID(), name: uniqueName(name, skip: nil),
                               ids: Array(ids.reduce(into: [String]()) { if !$0.contains($1) { $0.append($1) } }
                                   .prefix(AirportList.maxAirports)))
        lists.append(list)
        useList(list.id)
        persist()
        return list
    }

    func renameList(_ listID: String, to name: String) {
        guard let i = lists.firstIndex(where: { $0.id == listID }) else { return }
        lists[i].name = uniqueName(name, skip: listID)
        persist()
    }

    func deleteList(_ listID: String) {
        lists.removeAll { $0.id == listID }
        if activeListID == listID { useList(lists.first?.id) }
        persist()
    }

    func useList(_ listID: String?) {
        activeListID = listID
        UserDefaults.standard.set(listID, forKey: SettingsKey.activeList)
    }

    /// offsets are into the list's airports
    func move(in listID: String, from source: IndexSet, to destination: Int) {
        guard let i = lists.firstIndex(where: { $0.id == listID }) else { return }
        lists[i].ids.move(fromOffsets: source, toOffset: destination)
        persist()
    }

    func setHome(_ id: String?) {
        home = id
        UserDefaults.standard.set(id, forKey: SettingsKey.home)
        persist()
    }

    private func uniqueName(_ raw: String, skip: String?) -> String {
        let base = String(raw.trimmingCharacters(in: .whitespacesAndNewlines).prefix(60))
        let name = base.isEmpty ? "My airports" : base
        var candidate = name, n = 2
        while lists.contains(where: { $0.id != skip && $0.name.lowercased() == candidate.lowercased() }) {
            candidate = "\(name.prefix(56)) \(n)"
            n += 1
        }
        return candidate
    }

    private static func newID() -> String { String(UUID().uuidString.prefix(8)).lowercased() }

    private func persist() {
        let d = UserDefaults.standard
        if let data = try? JSONEncoder().encode(lists) { d.set(data, forKey: SettingsKey.lists) }
        // background alerts read this: every airport you keep, home included
        d.set(saved, forKey: SettingsKey.saved)
    }
}

/// one list of airports ("Club SVFR", "Bahamas trip"), the same shape as the site's
struct AirportList: Codable, Identifiable, Hashable, Sendable {
    let id: String
    var name: String
    var ids: [String]

    static let maxAirports = 200

    /// amend.watch/list/?w=DAB,VRB&n=Club%20SVFR: anyone can open it, and save it on the site
    var shareURL: URL? {
        var c = URLComponents(url: API.base.appending(path: "list/"), resolvingAgainstBaseURL: false)
        c?.queryItems = [URLQueryItem(name: "w", value: ids.joined(separator: ",")),
                         URLQueryItem(name: "n", value: name)]
        return c?.url
    }
}
