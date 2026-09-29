// Not a standalone buildable project on its own — this declares the
// `consentbridge` library module for inclusion in a consuming app's own
// settings.gradle.kts via:
//   include(":consentbridge")
//   project(":consentbridge").projectDir = file("path/to/sdk/mobile/android/consentbridge")
rootProject.name = "consentbridge-android"
include(":consentbridge")
