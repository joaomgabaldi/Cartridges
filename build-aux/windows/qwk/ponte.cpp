// Ponte entre o PySide6 e o QWindowKit: registra os tipos QML do QWindowKit
// (WindowAgent) no motor QML criado pelo Python. O Python passa o ponteiro C++
// do motor (shiboken6.getCppPointer) por ctypes; não há binding gerado.

#include <QtCore/QtVersion>
#include <QtQml/QQmlEngine>
#include <QWKQuick/qwkquickglobal.h>

#include <cstring>

// O QWindowKit usa a API privada do Qt, cujo layout muda até entre versões de
// correção: com o Qt do PySide6 diferente do usado aqui, a memória se corromperia
// em silêncio. Por isso recusa (devolve 0) se as versões não forem idênticas.
extern "C" __declspec(dllexport) int qwk_registrar(void *motor) {
    if (std::strcmp(qVersion(), QT_VERSION_STR) != 0)
        return 0;
    QWK::registerTypes(static_cast<QQmlEngine *>(motor));
    return 1;
}
