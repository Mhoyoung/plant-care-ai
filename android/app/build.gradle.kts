plugins {
    id("com.android.application")
}

android {
    namespace = "com.mhoyoung.plantcareai"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.mhoyoung.plantcareai"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.activity:activity:1.9.3")
}
