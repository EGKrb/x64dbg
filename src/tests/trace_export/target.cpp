#include <windows.h>

volatile unsigned int counter = 0;

int main()
{
    for(int i = 0; i < 1000; i++)
        counter += i;
    return 0;
}
