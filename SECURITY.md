# Security Policy

## Supported Versions

This project is actively maintained. Security updates are applied to the following versions:

| Version | Supported          |
| ------- | ------------------ |
| main    | ✅ Active support  |
| < 1.0   | ✅ Active support  |

## Reporting a Vulnerability

We take the security of this project seriously. If you discover a security vulnerability, please report it responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via GitHub's private vulnerability reporting feature:

1. Go to the [Security Advisories](https://github.com/danalec/scoop-alts/security/advisories) page
2. Click "Report a vulnerability"
3. Fill in the details of the vulnerability

Alternatively, you can email the maintainer directly if GitHub's security feature is unavailable.

### What to Include

Please include the following information in your report:

- **Description** of the vulnerability
- **Steps to reproduce** the issue
- **Potential impact** of the vulnerability
- **Suggested fix** (if you have one)
- **Your contact information** for follow-up

### Response Timeline

- **Initial response**: Within 48 hours
- **Status update**: Within 7 days
- **Resolution target**: Critical vulnerabilities within 30 days

### Disclosure Policy

- We follow [responsible disclosure](https://en.wikipedia.org/wiki/Responsible_disclosure) practices
- We ask that you give us reasonable time to fix the issue before public disclosure
- We will credit you in the security advisory (unless you prefer to remain anonymous)

## Security Best Practices

### For Users

1. **Verify manifests**: Review manifest files before installing packages
2. **Check hashes**: Ensure downloaded files match the expected hashes
3. **Keep updated**: Regularly run `scoop update` to get security fixes
4. **Review scripts**: Check update scripts before running them locally

### For Contributors

1. **No hardcoded secrets**: Never commit API keys, tokens, or passwords
2. **Use environment variables**: Store sensitive configuration in environment variables
3. **Validate inputs**: Sanitize and validate all external inputs
4. **Secure dependencies**: Keep dependencies updated and monitor for vulnerabilities

## Security Features

This project includes several security-conscious design decisions:

### Manifest Validation

All manifests are validated against a JSON schema to ensure:
- Required fields are present
- URLs use HTTPS where possible
- Hash values are properly formatted

### Dependency Scanning

We use automated tools to scan for vulnerable dependencies:
- GitHub Dependabot alerts
- Pre-commit hooks for linting

### Secure Defaults

- Webhook URLs are configurable via environment variables
- No sensitive data is logged
- Git operations use secure protocols

## Known Security Considerations

### Download URLs

Some packages may download from external sources. Users should:
- Verify the source URL in manifests
- Check that hashes match after download
- Be cautious with packages from untrusted sources

### Registry Modifications

Some packages (like ungoogled-chromium) may modify Windows registry settings for default browser functionality. These changes are:
- Documented in the manifest
- Reversible via uninstall
- User-initiated (opt-in)

### Script Execution

Update scripts make network requests to check for new versions. These scripts:
- Use HTTPS for all requests
- Respect rate limits
- Do not execute arbitrary code from external sources

## Security Updates

Security updates are released as needed and announced via:

- GitHub Security Advisories
- Release notes
- Commit messages with `security:` prefix

## Contact

For security-related questions or concerns:

- Open a GitHub Security Advisory (preferred)
- Email the maintainer for sensitive issues

---

Thank you for helping keep scoop-alts secure! 🔒
