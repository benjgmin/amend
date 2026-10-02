import Foundation

/// a list someone shared: an amend.watch/list/?w=BJC,VRB&n=Flying%20club link, a named list link
/// (amend.watch/list/flying-club/), or just airport IDs ("BJC, kfdk PHNL")
struct SharedList: Sendable {
    let name: String
    let ids: [String]

    enum Failure: LocalizedError {
        case nothing, notFound
        var errorDescription: String? {
            switch self {
            case .nothing: "That doesn't look like an Amend list link or airport IDs."
            case .notFound: "Couldn't open that list. Check the link and try again."
            }
        }
    }

    static func read(_ raw: String) async throws -> SharedList {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        // "amend.watch/list/?w=..." pasted without https://
        if text.lowercased().hasPrefix("amend.watch/") || text.lowercased().hasPrefix("www.amend.watch/") {
            text = "https://" + text
        }
        if let url = URL(string: text), let host = url.host(), host.hasSuffix("amend.watch") {
            let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let name = items.first { $0.name == "n" }?.value ?? ""
            if let w = items.first(where: { $0.name == "w" })?.value {
                let ids = parse(w)
                guard !ids.isEmpty else { throw Failure.nothing }
                return SharedList(name: name.isEmpty ? "Shared list" : name, ids: ids)
            }
            // a named list: its page carries the airports (the same data its "Save to my lists" button uses)
            let parts = url.path().split(separator: "/")
            if parts.count >= 2, parts[0] == "list" {
                return try await named(String(parts[1]).lowercased())
            }
            throw Failure.nothing
        }
        let ids = parse(text)
        guard !ids.isEmpty else { throw Failure.nothing }
        return SharedList(name: "Shared list", ids: ids)
    }

    /// "BJC, kfdk PHNL" -> ["BJC", "FDK", "PHNL"], 200 at most, like the site
    static func parse(_ s: String) -> [String] {
        var out: [String] = []
        for token in s.split(whereSeparator: { $0 == "," || $0 == ";" || $0.isWhitespace }) {
            if let id = AirportStore.normalize(String(token)), !out.contains(id) { out.append(id) }
        }
        return Array(out.prefix(AirportList.maxAirports))
    }

    private static func named(_ slug: String) async throws -> SharedList {
        guard slug.allSatisfy({ $0.isLetter || $0.isNumber || $0 == "-" }),
              let data = try await API.data("list/\(slug)/"),
              let html = String(data: data, encoding: .utf8),
              let ids = attribute("data-ids", in: html).map(parse), !ids.isEmpty
        else { throw Failure.notFound }
        return SharedList(name: attribute("data-name", in: html) ?? slug, ids: ids)
    }

    private static func attribute(_ name: String, in html: String) -> String? {
        guard let start = html.range(of: "\(name)=\""),
              let end = html[start.upperBound...].firstIndex(of: "\"") else { return nil }
        return String(html[start.upperBound..<end])
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#x27;", with: "'")
            .replacingOccurrences(of: "&#39;", with: "'")
            .replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&amp;", with: "&")
    }
}
