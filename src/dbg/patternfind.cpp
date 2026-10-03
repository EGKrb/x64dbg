#include "patternfind.h"
#include <vector>
#include <algorithm>
#include <memory>

using std::string;
using std::vector;

static inline bool isHex(char ch)
{
    return (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'F') || (ch >= 'a' && ch <= 'f');
}

static inline string formathexpattern(const string & patterntext)
{
    string result;
    int len = (int)patterntext.length();
    for(int i = 0; i < len; i++)
        if(patterntext[i] == '?' || isHex(patterntext[i]))
            result += patterntext[i];
    return result;
}

static inline int hexchtoint(char ch)
{
    if(ch >= '0' && ch <= '9')
        return ch - '0';
    else if(ch >= 'A' && ch <= 'F')
        return ch - 'A' + 10;
    else if(ch >= 'a' && ch <= 'f')
        return ch - 'a' + 10;
    return -1;
}

bool patterntransform(const string & patterntext, vector<PatternByte> & pattern)
{
    pattern.clear();

    //reject patterns with unsupported charcters
    for(char ch : patterntext)
        if(ch != '?' && ch != ' ' && !isHex(ch))
            return false;

    string formattext = formathexpattern(patterntext);
    int len = (int)formattext.length();
    if(!len)
        return false;

    if(len % 2) //not a multiple of 2
    {
        formattext += '?';
        len++;
    }

    PatternByte newByte = {};
    for(int i = 0, j = 0; i < len; i++)
    {
        int shift = j ? 0 : 4;

        if(formattext[i] != '?')
        {
            newByte.data |= (hexchtoint(formattext[i]) & 0xF) << shift;
            newByte.mask |= 0xf << shift;
        }

        j++;
        if(j == 2) //two nibbles = one byte
        {
            j = 0;
            pattern.push_back(newByte);
            newByte = {};
        }
    }

    //reject wildcard only patterns
    bool allWildcard = std::all_of(pattern.begin(), pattern.end(), [](const PatternByte & patternByte)
    {
        return patternByte.mask == 0x00;
    });
    if(allWildcard)
        return false;

    return true;
}

size_t patternfind(const unsigned char* data, size_t datasize, const char* pattern, int* patternsize)
{
    string patterntext(pattern);
    vector<PatternByte> searchpattern;
    if(!patterntransform(patterntext, searchpattern))
        return -1;
    return patternfind(data, datasize, searchpattern);
}

static inline void patternwritebyte(unsigned char* byte, const PatternByte & pbyte)
{
    *byte = pbyte.data | (*byte & ~pbyte.mask);
}

void patternwrite(unsigned char* data, size_t datasize, const char* pattern)
{
    vector<PatternByte> writepattern;
    string patterntext(pattern);
    if(!patterntransform(patterntext, writepattern))
        return;
    size_t writepatternsize = writepattern.size();
    if(writepatternsize > datasize)
        writepatternsize = datasize;
    for(size_t i = 0; i < writepatternsize; i++)
        patternwritebyte(&data[i], writepattern.at(i));
}

bool patternsnr(unsigned char* data, size_t datasize, const char* searchpattern, const char* replacepattern)
{
    size_t found = patternfind(data, datasize, searchpattern);
    if(found == -1)
        return false;
    patternwrite(data + found, datasize - found, replacepattern);
    return true;
}

struct PatternNeedle
{
    unsigned char data;
    unsigned char mask;
    size_t offset;
};

size_t patternfind(const unsigned char* data, size_t datasize, const std::vector<PatternByte>& pattern)
{
    size_t searchpatternsize = pattern.size();

    if(datasize < searchpatternsize)
        return -1;

    std::unique_ptr<PatternNeedle[]> const needles(new PatternNeedle[searchpatternsize]);
    size_t n_needles = 0;

    // Collect all of the literal bytes.
    // The less common bytes tend to be at the end, so iterate back-to-front.
    for(size_t i = searchpatternsize; i--;)
    {
        if(pattern[i].mask == 0xFF)
            needles[n_needles++] = { pattern[i].data, pattern[i].mask, i };
    }

    size_t literals = n_needles;

    // Don't forget the partially masked bytes.
    for(size_t i = searchpatternsize; i--;)
    {
        if(pattern[i].mask != 0x00 && pattern[i].mask != 0xFF)
            needles[n_needles++] = { pattern[i].data, pattern[i].mask, i };
    }

    if(n_needles == 0)
        return -1;

    const unsigned char* here = data;
    const unsigned char* end = &data[datasize - (searchpatternsize - 1)];

    do
    {
        if(literals)
        {
            PatternNeedle needle = needles[0];

            // On Windows, memchr is not as fast as it could be, so MSVC's std::find uses its own SIMD implementation.
            here = std::find(here + needle.offset, end + needle.offset, needle.data) - needle.offset;
            if(here == end)
                break;

            for(size_t i = 1; i < literals; ++i)
            {
                needle = needles[i];

                if(here[needle.offset] != needle.data)
                {
                    // Swap this mismatched needle with the previously matched one.
                    // By constantly re-adjusting the order of the needles, the least common one should be moved to the front,
                    // maximizing the time spent inside std::find, and minimizing the time spent checking the rest of the bytes.
                    needles[i] = needles[i - 1];
                    needles[i - 1] = needle;
                    goto skip;
                }
            }
        }

        for(size_t i = literals; i < n_needles; ++i)
        {
            PatternNeedle needle = needles[i];

            if((here[needle.offset] & needle.mask) != needle.data)
                goto skip;
        }

        return here - data;

skip:
        ++here;
    }
    while(here != end);

    return -1;
}