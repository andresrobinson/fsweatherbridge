# Contributing to FSX Weather Bridge

Thank you for your interest in contributing to FSX Weather Bridge! This document provides guidelines and instructions for contributing.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/your-username/fsweatherbridge.git
   cd fsweatherbridge
   ```
3. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

1. **Install Python 3.12 (32-bit)**
   - ⚠️ Must be 32-bit version (required for FSUIPC compatibility)
   - Verify: `python -VV` should show `Python 3.12.x (32-bit)`

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```bash
   python -m src.main
   ```

## Code Style

- Follow PEP 8 Python style guide
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and small
- Add comments for complex logic

## Testing

- Run existing tests:
  ```bash
  python -m pytest tests/
  ```
- Add tests for new features
- Ensure all tests pass before submitting

## Submitting Changes

1. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Description of your changes"
   ```
   - Use clear, descriptive commit messages
   - Reference issues if applicable (e.g., "Fix #123: Description")

2. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

3. **Create a Pull Request** on GitHub
   - Provide a clear description of your changes
   - Reference any related issues
   - Include screenshots if UI changes

## Pull Request Guidelines

- **Title**: Clear, concise description
- **Description**: 
  - What changes were made
  - Why the changes were made
  - How to test the changes
  - Screenshots (if applicable)
- **Code Quality**:
  - Code follows style guidelines
  - Tests pass
  - Documentation updated (if needed)

## Areas for Contribution

- **Bug Fixes**: Fix issues reported in GitHub Issues
- **Features**: Implement new features (discuss in Issues first)
- **Documentation**: Improve or expand documentation
- **Testing**: Add tests for existing or new code
- **Performance**: Optimize code for better performance
- **UI/UX**: Improve web interface design and usability

## Reporting Issues

When reporting issues, please include:
- **Description**: Clear description of the issue
- **Steps to Reproduce**: Detailed steps to reproduce
- **Expected Behavior**: What should happen
- **Actual Behavior**: What actually happens
- **Environment**:
  - Python version: `python -VV`
  - Windows version
  - FSX version
  - FSUIPC4 version
- **Logs**: Relevant log files from `logs/` directory
- **Screenshots**: If applicable

## Code of Conduct

- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on constructive feedback
- Respect different viewpoints and experiences

## Questions?

If you have questions about contributing:
- Open an issue on GitHub
- Check existing documentation in `Docs/` folder
- Review existing code for examples

Thank you for contributing to FSX Weather Bridge! 🎉
