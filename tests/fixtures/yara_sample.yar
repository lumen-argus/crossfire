rule Detect_AWS_Key : credential cloud
{
    meta:
        author = "Security Team"
        description = "Detects AWS access key IDs"
        severity = "high"

    strings:
        $access_key = /(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}/
        $secret_key = /[A-Za-z0-9\/+=]{40}/ ascii wide

    condition:
        any of them
}

rule Detect_Base64_Credentials
{
    meta:
        description = "Detects base64-encoded credential patterns"
        severity = "medium"

    strings:
        $b64_password = /(?:password|passwd|pwd)\s*[:=]\s*[A-Za-z0-9+\/]{16,}={0,2}/ nocase
        $text_string = "not a regex"
        $hex_string = { 4D 5A 90 00 }
        $b64_token = /(?:token|bearer|api[_-]?key)\s*[:=]\s*[A-Za-z0-9+\/]{20,}={0,2}/ nocase

    condition:
        any of ($b64_password, $b64_token)
}

// Rule without regex strings — should be skipped
rule Text_Only_Rule
{
    meta:
        description = "Only text strings"

    strings:
        $text = "malware_signature"

    condition:
        $text
}
