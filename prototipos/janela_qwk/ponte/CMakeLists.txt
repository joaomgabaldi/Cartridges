cmake_minimum_required(VERSION 3.20)
project(qwk_ponte LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
# O QWindowKit estático leva os módulos privados na interface de link.
find_package(Qt6 REQUIRED COMPONENTS Core Gui Qml Quick CorePrivate GuiPrivate QuickPrivate)
find_package(QWindowKit REQUIRED COMPONENTS Core Quick)

add_library(qwk_ponte SHARED ponte.cpp)
target_link_libraries(qwk_ponte PRIVATE Qt6::Qml QWindowKit::Quick)
install(TARGETS qwk_ponte RUNTIME DESTINATION .)
